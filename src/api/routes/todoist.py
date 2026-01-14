"""Todoist integration routes: OAuth connection, status, disconnection.

This module handles Todoist OAuth flow and connection management.
"""

import uuid
from typing import Any

from apiflask import APIBlueprint

from src.api.errors import raise_not_found_error, raise_validation_error
from src.api.schemas import (
    StatusResponse,
    TodoistAuthUrlResponse,
    TodoistConnectRequest,
    TodoistConnectResponse,
    TodoistStatusResponse,
)
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.auth.todoist_auth import (
    TodoistAuthError,
    exchange_code_for_token,
    get_authorization_url,
)
from src.auth.todoist_auth import (
    get_user_info as get_todoist_user_info,
)
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)

auth = APIBlueprint("todoist", __name__, url_prefix="/auth", tag="Todoist")


# ============================================================================
# Todoist Integration Routes
# ============================================================================


@auth.route("/todoist/auth-url", methods=["GET"])
@auth.output(TodoistAuthUrlResponse)
@auth.doc(responses=[401])
@require_auth
def get_todoist_auth_url(user: User) -> dict[str, str]:
    """Get Todoist OAuth authorization URL.

    Returns a URL to redirect the user to for Todoist authorization.
    The state token should be stored and validated on callback.
    """
    # Generate a unique state token for CSRF protection
    state = str(uuid.uuid4())
    # Store state in session or return to client for validation
    # For simplicity, we return it and let the client store/validate it
    auth_url = get_authorization_url(state)

    logger.debug("Generated Todoist auth URL", extra={"user_id": user.id})
    return {"auth_url": auth_url, "state": state}


@auth.route("/todoist/connect", methods=["POST"])
@auth.output(TodoistConnectResponse)
@auth.doc(responses=[400, 401])
@require_auth
@validate_request(TodoistConnectRequest)
def connect_todoist(user: User, data: TodoistConnectRequest) -> dict[str, Any]:
    """Connect Todoist account by exchanging OAuth code for access token.

    The frontend should:
    1. Call GET /auth/todoist/auth-url to get the authorization URL and state
    2. Redirect user to the authorization URL
    3. After user authorizes, Todoist redirects back with code and state
    4. Frontend validates state matches, then calls this endpoint with code
    """
    logger.info("Todoist connection attempt", extra={"user_id": user.id})

    try:
        # Exchange code for access token
        access_token = exchange_code_for_token(data.code)

        # Get Todoist user info to confirm connection
        todoist_user = get_todoist_user_info(access_token)
        todoist_email = todoist_user.get("email")

        # Store the access token
        db.update_user_todoist_token(user.id, access_token)

        logger.info(
            "Todoist connected successfully",
            extra={"user_id": user.id, "todoist_email": todoist_email},
        )
        return {"connected": True, "todoist_email": todoist_email}

    except TodoistAuthError as e:
        logger.warning(
            "Todoist connection failed",
            extra={"user_id": user.id, "error": str(e)},
        )
        raise_validation_error(str(e))


@auth.route("/todoist/disconnect", methods=["POST"])
@auth.output(StatusResponse)
@auth.doc(responses=[401])
@require_auth
def disconnect_todoist(user: User) -> dict[str, str]:
    """Disconnect Todoist account.

    Removes the stored access token. Note that the user must manually
    revoke access in Todoist settings if they want to fully disconnect.
    """
    logger.info("Todoist disconnection requested", extra={"user_id": user.id})

    db.update_user_todoist_token(user.id, None)

    logger.info("Todoist disconnected", extra={"user_id": user.id})
    return {"status": "disconnected"}


@auth.route("/todoist/status", methods=["GET"])
@auth.output(TodoistStatusResponse)
@auth.doc(responses=[401])
@require_auth
def get_todoist_status(user: User) -> dict[str, Any]:
    """Get current Todoist connection status.

    Returns whether Todoist is connected, and if so, the connected email.
    Also detects invalid tokens and reports needs_reconnect=True.
    """
    # Refresh user data to get latest Todoist fields
    current_user = db.get_user_by_id(user.id)
    if not current_user:
        raise_not_found_error("User")

    connected = bool(current_user.todoist_access_token)
    todoist_email = None
    connected_at = None
    needs_reconnect = False

    if connected and current_user.todoist_access_token:
        # Fetch Todoist user info to validate token and get email
        try:
            todoist_user = get_todoist_user_info(current_user.todoist_access_token)
            todoist_email = todoist_user.get("email")
        except TodoistAuthError:
            # Token is invalid - user needs to reconnect
            logger.warning(
                "Todoist token invalid - user needs to reconnect",
                extra={"user_id": user.id},
            )
            needs_reconnect = True

        if current_user.todoist_connected_at:
            connected_at = current_user.todoist_connected_at.isoformat()

    return {
        "connected": connected,
        "todoist_email": todoist_email,
        "connected_at": connected_at,
        "needs_reconnect": needs_reconnect,
    }
