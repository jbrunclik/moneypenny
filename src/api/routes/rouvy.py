"""Rouvy integration routes: connect (email/password), status, disconnect.

Rouvy has no OAuth/API; connect drives a headless login and stores the session
cookie plus the credentials (Fernet-encrypted) so the session can be
auto-refreshed. No MFA (Rouvy's flow has none).
"""

from typing import Any

from apiflask import APIBlueprint

from src.api.errors import raise_not_found_error, raise_validation_error
from src.api.schemas import (
    RouvyConnectRequest,
    RouvyConnectResponse,
    RouvyStatusResponse,
    StatusResponse,
)
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.auth.rouvy_auth import RouvyAuthError, cookies_to_jar, login
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)

auth = APIBlueprint("rouvy", __name__, url_prefix="/auth", tag="Rouvy")


@auth.route("/rouvy/connect", methods=["POST"])
@auth.output(RouvyConnectResponse)
@auth.doc(responses=[400, 401])
@require_auth
@validate_request(RouvyConnectRequest)
def connect_rouvy(user: User, data: RouvyConnectRequest) -> dict[str, Any]:
    """Connect Rouvy: headless login, then store session + encrypted credentials."""
    logger.info("Rouvy connection attempt", extra={"user_id": user.id})
    try:
        session = login(data.email, data.password)
    except RouvyAuthError as e:
        logger.warning("Rouvy connection failed", extra={"user_id": user.id, "error": str(e)})
        raise_validation_error(str(e))
    db.update_user_rouvy_credentials(user.id, data.email, data.password, session)
    logger.info("Rouvy connected", extra={"user_id": user.id})
    return {"connected": True}


@auth.route("/rouvy/disconnect", methods=["POST"])
@auth.output(StatusResponse)
@auth.doc(responses=[401])
@require_auth
def disconnect_rouvy(user: User) -> dict[str, str]:
    """Disconnect Rouvy by clearing stored credentials + session."""
    db.update_user_rouvy_credentials(user.id, None, None, None)
    logger.info("Rouvy disconnected", extra={"user_id": user.id})
    return {"status": "disconnected"}


@auth.route("/rouvy/status", methods=["GET"])
@auth.output(RouvyStatusResponse)
@auth.doc(responses=[401])
@require_auth
def get_rouvy_status(user: User) -> dict[str, Any]:
    """Report Rouvy connection status."""
    current = db.get_user_by_id(user.id)
    if not current:
        raise_not_found_error("User")
    connected = bool(current.rouvy_session)
    needs_reconnect = connected and not cookies_to_jar(current.rouvy_session or "")
    connected_at = (
        current.rouvy_connected_at.isoformat() if connected and current.rouvy_connected_at else None
    )
    return {
        "connected": connected,
        "connected_at": connected_at,
        "needs_reconnect": needs_reconnect,
    }
