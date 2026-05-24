"""Garmin Connect integration routes: connection, MFA, status, disconnection.

Unlike Todoist/Calendar (OAuth redirect flow), Garmin uses email/password
login. The password is never stored — only session tokens.

The MFA flow is fully stateless on the backend: the frontend keeps the
credentials in memory between the connect attempt and the MFA submit, then
POSTs {email, password, mfa_code} together. The backend then runs a single
full login with garminconnect's ``prompt_mfa`` callback. This avoids needing
to share partially-authenticated client state across gunicorn workers — that
state contains curl_cffi sessions and thread locks that cannot be pickled.
"""

from typing import Any

from apiflask import APIBlueprint

from src.api.errors import raise_not_found_error, raise_validation_error
from src.api.schemas import (
    GarminConnectRequest,
    GarminConnectResponse,
    GarminMfaRequest,
    GarminStatusResponse,
    StatusResponse,
)
from src.api.validation import validate_request
from src.auth.garmin_auth import (
    GarminAuthError,
    GarminMfaRequired,
    authenticate,
    authenticate_with_mfa,
    create_client_from_tokens,
)
from src.auth.jwt_auth import require_auth
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)

auth = APIBlueprint("garmin", __name__, url_prefix="/auth", tag="Garmin")


@auth.route("/garmin/connect", methods=["POST"])
@auth.output(GarminConnectResponse)
@auth.doc(responses=[400, 401])
@require_auth
@validate_request(GarminConnectRequest)
def connect_garmin(user: User, data: GarminConnectRequest) -> dict[str, Any]:
    """Connect Garmin account with email and password.

    The password is used only for the live login attempt and is never stored.
    Only serialized session tokens are persisted in the database.

    Returns ``mfa_required=True`` if the account has MFA enabled. In that
    case, the frontend should prompt for the verification code and call
    POST /auth/garmin/mfa with email, password, and the code together.
    """
    logger.info("Garmin connection attempt", extra={"user_id": user.id})

    try:
        tokens, display_name = authenticate(data.email, data.password)

        db.update_user_garmin_token(user.id, tokens)

        logger.info(
            "Garmin connected successfully",
            extra={"user_id": user.id, "display_name": display_name},
        )
        return {"connected": True, "mfa_required": False, "display_name": display_name}

    except GarminMfaRequired:
        logger.info("Garmin MFA required", extra={"user_id": user.id})
        return {"connected": False, "mfa_required": True, "display_name": None}

    except GarminAuthError as e:
        logger.warning(
            "Garmin connection failed",
            extra={"user_id": user.id, "error": str(e)},
        )
        raise_validation_error(str(e))


@auth.route("/garmin/mfa", methods=["POST"])
@auth.output(GarminConnectResponse)
@auth.doc(responses=[400, 401])
@require_auth
@validate_request(GarminMfaRequest)
def garmin_mfa(user: User, data: GarminMfaRequest) -> dict[str, Any]:
    """Complete Garmin login by re-submitting credentials together with the
    MFA verification code. Runs the full login in a single request so no
    cross-worker state is needed.
    """
    logger.info("Garmin MFA attempt", extra={"user_id": user.id})

    try:
        tokens, display_name = authenticate_with_mfa(data.email, data.password, data.mfa_code)

        db.update_user_garmin_token(user.id, tokens)

        logger.info("Garmin MFA completed", extra={"user_id": user.id})
        return {"connected": True, "mfa_required": False, "display_name": display_name}

    except GarminAuthError as e:
        logger.warning(
            "Garmin MFA failed",
            extra={"user_id": user.id, "error": str(e)},
        )
        raise_validation_error(str(e))


@auth.route("/garmin/disconnect", methods=["POST"])
@auth.output(StatusResponse)
@auth.doc(responses=[401])
@require_auth
def disconnect_garmin(user: User) -> dict[str, str]:
    """Disconnect Garmin account by clearing stored tokens."""
    logger.info("Garmin disconnection requested", extra={"user_id": user.id})

    db.update_user_garmin_token(user.id, None)

    logger.info("Garmin disconnected", extra={"user_id": user.id})
    return {"status": "disconnected"}


@auth.route("/garmin/status", methods=["GET"])
@auth.output(GarminStatusResponse)
@auth.doc(responses=[401])
@require_auth
def get_garmin_status(user: User) -> dict[str, Any]:
    """Get current Garmin connection status.

    Returns whether Garmin is connected. If connected, validates the
    stored tokens and reports needs_reconnect=True if expired.
    """
    current_user = db.get_user_by_id(user.id)
    if not current_user:
        raise_not_found_error("User")

    connected = bool(current_user.garmin_token)
    connected_at = None
    needs_reconnect = False

    if connected and current_user.garmin_token:
        try:
            create_client_from_tokens(current_user.garmin_token)
        except GarminAuthError:
            logger.warning(
                "Garmin token invalid - user needs to reconnect",
                extra={"user_id": user.id},
            )
            needs_reconnect = True

        if current_user.garmin_connected_at:
            connected_at = current_user.garmin_connected_at.isoformat()

    return {
        "connected": connected,
        "connected_at": connected_at,
        "needs_reconnect": needs_reconnect,
    }
