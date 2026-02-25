"""Garmin Connect integration routes: connection, MFA, status, disconnection.

Unlike Todoist/Calendar (OAuth redirect flow), Garmin uses email/password
login via garth. The password is never stored — only session tokens.
"""

import time
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
    complete_mfa_login,
    create_client_from_tokens,
)
from src.auth.jwt_auth import require_auth
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)

auth = APIBlueprint("garmin", __name__, url_prefix="/auth", tag="Garmin")

# In-memory MFA pending state (keyed by user_id, 5-min TTL)
# Fine for single-instance architecture
_mfa_pending: dict[str, dict[str, Any]] = {}
MFA_TTL_SECONDS = 300  # 5 minutes


def _cleanup_expired_mfa() -> None:
    """Remove expired MFA entries."""
    now = time.time()
    expired = [
        uid for uid, data in _mfa_pending.items() if now - data["created_at"] > MFA_TTL_SECONDS
    ]
    for uid in expired:
        del _mfa_pending[uid]


@auth.route("/garmin/connect", methods=["POST"])
@auth.output(GarminConnectResponse)
@auth.doc(responses=[400, 401])
@require_auth
@validate_request(GarminConnectRequest)
def connect_garmin(user: User, data: GarminConnectRequest) -> dict[str, Any]:
    """Connect Garmin account with email and password.

    The password is used only for garth login and is never stored.
    Only serialized session tokens are persisted in the database.

    May return mfa_required=True if the account has MFA enabled.
    In that case, call POST /auth/garmin/mfa with the verification code.
    """
    logger.info("Garmin connection attempt", extra={"user_id": user.id})
    _cleanup_expired_mfa()

    try:
        tokens, display_name = authenticate(data.email, data.password)

        # Store tokens
        db.update_user_garmin_token(user.id, tokens)

        logger.info(
            "Garmin connected successfully",
            extra={"user_id": user.id, "display_name": display_name},
        )
        return {"connected": True, "mfa_required": False, "display_name": display_name}

    except GarminMfaRequired as e:
        # Store pending MFA state (garmin client + context for resume_login)
        _mfa_pending[user.id] = {
            "garmin": e.garmin,
            "mfa_context": e.mfa_context,
            "created_at": time.time(),
        }
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
    """Complete Garmin MFA login with verification code.

    Must be called after POST /auth/garmin/connect returns mfa_required=True.
    The MFA session expires after 5 minutes.
    """
    logger.info("Garmin MFA attempt", extra={"user_id": user.id})
    _cleanup_expired_mfa()

    pending = _mfa_pending.pop(user.id, None)
    if not pending:
        raise_validation_error("No pending MFA session. Please start the connection again.")

    try:
        tokens, display_name = complete_mfa_login(
            pending["garmin"], pending["mfa_context"], data.mfa_code
        )

        # Store tokens
        db.update_user_garmin_token(user.id, tokens)

        logger.info("Garmin MFA completed", extra={"user_id": user.id})
        return {"connected": True, "mfa_required": False, "display_name": display_name}

    except GarminAuthError as e:
        _mfa_pending[user.id] = pending  # Re-store so user can retry
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
        # Try to create client from tokens to verify they work
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
