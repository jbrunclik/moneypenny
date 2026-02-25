"""Google Calendar integration routes: OAuth, status, calendar selection.

This module handles Google Calendar OAuth flow and calendar management.
IMPORTANT: _get_valid_calendar_access_token is exported for use by planner and chat routes.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from apiflask import APIBlueprint

from src.api.errors import raise_not_found_error, raise_validation_error
from src.api.schemas import (
    CalendarListResponse,
    GoogleCalendarAuthUrlResponse,
    GoogleCalendarConnectRequest,
    GoogleCalendarConnectResponse,
    GoogleCalendarStatusResponse,
    SelectedCalendarsResponse,
    StatusResponse,
    UpdateSelectedCalendarsRequest,
)
from src.api.validation import validate_request
from src.auth.google_calendar import (
    GoogleCalendarAuthError,
)
from src.auth.google_calendar import (
    exchange_code_for_tokens as exchange_calendar_code_for_tokens,
)
from src.auth.google_calendar import (
    get_authorization_url as get_google_calendar_auth_url,
)
from src.auth.google_calendar import (
    get_user_info as get_google_calendar_user_info,
)
from src.auth.google_calendar import (
    refresh_access_token as refresh_google_calendar_token,
)
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)

auth = APIBlueprint("calendar", __name__, url_prefix="/auth", tag="Calendar")


# ============================================================================
# Helper Functions (exported for use by planner and chat routes)
# ============================================================================


def _is_google_calendar_configured() -> bool:
    return bool(Config.GOOGLE_CALENDAR_CLIENT_ID and Config.GOOGLE_CALENDAR_CLIENT_SECRET)


def _compute_calendar_expiry(expires_in: Any) -> datetime:
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        seconds = 3600
    # Subtract one minute to refresh proactively
    seconds = max(60, seconds - 60)
    return datetime.now() + timedelta(seconds=seconds)


def _get_valid_calendar_access_token(user: User) -> str | None:
    """Get a valid calendar access token, refreshing if needed.

    Returns None if calendar not connected or refresh fails.

    IMPORTANT: This function is exported for use by planner and chat routes.
    """
    current_user = db.get_user_by_id(user.id)
    if not current_user or not current_user.google_calendar_access_token:
        return None

    # Check if token expires soon (within 5 minutes)
    if current_user.google_calendar_token_expires_at:
        expires_at = current_user.google_calendar_token_expires_at
        refresh_threshold = datetime.now() + timedelta(minutes=5)
        if expires_at > refresh_threshold:
            return current_user.google_calendar_access_token

    # Need to refresh
    if not current_user.google_calendar_refresh_token:
        return None

    try:
        refreshed = refresh_google_calendar_token(current_user.google_calendar_refresh_token)
        new_access_token: str = refreshed["access_token"]
        new_refresh_token = refreshed.get(
            "refresh_token", current_user.google_calendar_refresh_token
        )
        new_expires_at = _compute_calendar_expiry(refreshed.get("expires_in"))

        db.update_user_google_calendar_tokens(
            user.id,
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            expires_at=new_expires_at,
            email=current_user.google_calendar_email,
            connected_at=current_user.google_calendar_connected_at,
        )
        return new_access_token
    except GoogleCalendarAuthError as e:
        logger.error(
            "Failed to refresh calendar token", extra={"user_id": user.id, "error": str(e)}
        )
        return None


# ============================================================================
# Google Calendar Integration Routes
# ============================================================================


@auth.route("/calendar/auth-url", methods=["GET"])
@auth.output(GoogleCalendarAuthUrlResponse)
@auth.doc(responses=[401])
@require_auth
def get_calendar_auth_url(user: User) -> dict[str, str]:
    """Return the Google Calendar OAuth URL."""
    if not _is_google_calendar_configured():
        raise_validation_error("Google Calendar integration is not configured")

    state = str(uuid.uuid4())
    auth_url = get_google_calendar_auth_url(state)
    logger.debug("Generated Google Calendar auth URL", extra={"user_id": user.id})
    return {"auth_url": auth_url, "state": state}


@auth.route("/calendar/connect", methods=["POST"])
@auth.output(GoogleCalendarConnectResponse)
@auth.doc(responses=[400, 401])
@require_auth
@validate_request(GoogleCalendarConnectRequest)
def connect_google_calendar(user: User, data: GoogleCalendarConnectRequest) -> dict[str, Any]:
    """Connect Google Calendar via OAuth."""
    if not _is_google_calendar_configured():
        raise_validation_error("Google Calendar integration is not configured")

    logger.info("Google Calendar connection attempt", extra={"user_id": user.id})

    try:
        token_data = exchange_calendar_code_for_tokens(data.code)
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        if not access_token or not refresh_token:
            raise GoogleCalendarAuthError("Missing tokens from Google response")

        expires_at = _compute_calendar_expiry(token_data.get("expires_in"))

        profile = get_google_calendar_user_info(access_token)
        calendar_email = profile.get("email")

        db.update_user_google_calendar_tokens(
            user.id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            email=calendar_email,
        )

        # Reset selected calendars and clear cache when reconnecting with different account
        db.update_user_calendar_selected_ids(user.id, ["primary"])
        db.clear_calendar_cache(user.id)

        logger.info(
            "Google Calendar connected",
            extra={"user_id": user.id, "calendar_email": calendar_email},
        )
        return {"connected": True, "calendar_email": calendar_email}

    except GoogleCalendarAuthError as exc:
        logger.warning(
            "Google Calendar connection failed",
            extra={"user_id": user.id, "error": str(exc)},
        )
        raise_validation_error(str(exc))


@auth.route("/calendar/disconnect", methods=["POST"])
@auth.output(StatusResponse)
@auth.doc(responses=[401])
@require_auth
def disconnect_google_calendar(user: User) -> dict[str, str]:
    """Disconnect Google Calendar tokens."""
    logger.info("Google Calendar disconnection requested", extra={"user_id": user.id})
    db.update_user_google_calendar_tokens(user.id, None)

    # Reset selected calendar IDs to prevent stale IDs on reconnect with different account
    db.update_user_calendar_selected_ids(user.id, ["primary"])

    # Clear calendar cache to prevent stale data on reconnect
    db.clear_calendar_cache(user.id)

    logger.info("Google Calendar disconnected", extra={"user_id": user.id})
    return {"status": "disconnected"}


@auth.route("/calendar/status", methods=["GET"])
@auth.output(GoogleCalendarStatusResponse)
@auth.doc(responses=[401])
@require_auth
def get_google_calendar_status(user: User) -> dict[str, Any]:
    """Return Google Calendar connection status."""
    if not _is_google_calendar_configured():
        return {
            "connected": False,
            "calendar_email": None,
            "connected_at": None,
            "needs_reconnect": False,
        }

    current_user = db.get_user_by_id(user.id)
    if not current_user:
        raise_not_found_error("User")

    connected = bool(current_user.google_calendar_access_token)
    calendar_email = current_user.google_calendar_email
    connected_at = (
        current_user.google_calendar_connected_at.isoformat()
        if current_user.google_calendar_connected_at
        else None
    )
    needs_reconnect = False

    if connected and current_user.google_calendar_access_token:
        access_token = current_user.google_calendar_access_token
        expires_at = current_user.google_calendar_token_expires_at
        refresh_token = current_user.google_calendar_refresh_token

        # Proactively refresh if token expires within 5 minutes
        refresh_threshold = datetime.now() + timedelta(minutes=5)
        if expires_at and expires_at <= refresh_threshold:
            if refresh_token:
                try:
                    refreshed = refresh_google_calendar_token(refresh_token)
                    access_token = refreshed["access_token"]
                    new_refresh = refreshed.get("refresh_token", refresh_token)
                    expires_at = _compute_calendar_expiry(refreshed.get("expires_in"))
                    db.update_user_google_calendar_tokens(
                        user.id,
                        access_token=access_token,
                        refresh_token=new_refresh,
                        expires_at=expires_at,
                        email=calendar_email,
                        connected_at=current_user.google_calendar_connected_at,
                    )
                except GoogleCalendarAuthError:
                    needs_reconnect = True
                    logger.warning("Google Calendar refresh failed", extra={"user_id": user.id})
            else:
                needs_reconnect = True

        if not needs_reconnect:
            try:
                profile = get_google_calendar_user_info(access_token)
                calendar_email = profile.get("email") or calendar_email
            except GoogleCalendarAuthError:
                needs_reconnect = True

    return {
        "connected": connected,
        "calendar_email": calendar_email,
        "connected_at": connected_at,
        "needs_reconnect": needs_reconnect,
    }


@auth.route("/calendar/calendars", methods=["GET"])
@auth.output(CalendarListResponse)
@auth.doc(responses=[401])
@require_auth
def list_available_calendars(user: User) -> dict[str, Any]:
    """List all available Google Calendars for the current user."""
    if not _is_google_calendar_configured():
        return {"calendars": [], "error": "Google Calendar not configured"}

    # Get valid access token
    calendar_token = _get_valid_calendar_access_token(user)
    if not calendar_token:
        return {"calendars": [], "error": "Not connected"}

    # Check cache first (1 hour TTL)
    cached = db.get_cached_calendars(user.id)
    if cached:
        logger.debug("Returning cached calendars", extra={"user_id": user.id})
        return cached

    try:
        import requests

        headers = {"Authorization": f"Bearer {calendar_token}"}
        response = requests.get(
            f"{Config.GOOGLE_CALENDAR_API_BASE_URL}/users/me/calendarList",
            headers=headers,
            timeout=Config.GOOGLE_CALENDAR_API_TIMEOUT,
        )

        if response.status_code == 401:
            return {"calendars": [], "error": "Access expired. Please reconnect."}

        if response.status_code >= 400:
            logger.warning("Calendar list API error", extra={"status": response.status_code})
            return {"calendars": [], "error": f"API error ({response.status_code})"}

        data = response.json()
        calendars = [
            {
                "id": cal.get("id"),
                "summary": cal.get("summary"),
                "primary": cal.get("primary", False),
                "access_role": cal.get("accessRole"),
                "background_color": cal.get("backgroundColor"),
            }
            for cal in data.get("items", [])
        ]

        # Sort: primary first, then by name
        calendars.sort(key=lambda c: (not c["primary"], c["summary"].lower()))

        result = {"calendars": calendars}

        # Cache for 1 hour
        db.cache_calendars(user.id, result, ttl_seconds=3600)

        logger.info(
            "Fetched available calendars", extra={"user_id": user.id, "count": len(calendars)}
        )

        return result

    except requests.Timeout:
        logger.error("Calendar list timeout", extra={"user_id": user.id})
        return {"calendars": [], "error": "Request timeout"}
    except Exception as e:
        logger.error("Failed to list calendars", extra={"error": str(e)}, exc_info=True)
        return {"calendars": [], "error": "Failed to fetch calendars"}


@auth.route("/calendar/selected-calendars", methods=["GET"])
@auth.output(SelectedCalendarsResponse)
@auth.doc(responses=[401, 404])
@require_auth
def get_selected_calendars(user: User) -> dict[str, Any]:
    """Get the user's selected calendar IDs."""
    current_user = db.get_user_by_id(user.id)
    if not current_user:
        raise_not_found_error("User")

    selected = current_user.google_calendar_selected_ids or ["primary"]
    return {"calendar_ids": selected}


@auth.route("/calendar/selected-calendars", methods=["PUT"])
@auth.output(SelectedCalendarsResponse)
@auth.doc(responses=[400, 401, 404])
@require_auth
@validate_request(UpdateSelectedCalendarsRequest)
def update_selected_calendars(user: User, data: UpdateSelectedCalendarsRequest) -> dict[str, Any]:
    """Update the user's selected calendar IDs."""
    calendar_ids = data.calendar_ids

    # Update database (validation happens in the database method)
    success = db.update_user_calendar_selected_ids(user.id, calendar_ids)
    if not success:
        raise_not_found_error("User")

    # Invalidate dashboard cache so next fetch uses new selection
    db.invalidate_dashboard_cache(user.id)

    final_ids = calendar_ids if calendar_ids else ["primary"]
    logger.info("Updated calendar selection", extra={"user_id": user.id, "count": len(final_ids)})

    return {"calendar_ids": final_ids}
