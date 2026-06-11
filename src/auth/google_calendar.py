"""Google Calendar OAuth helpers."""

from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import requests

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_CALENDAR_SCOPES = " ".join(
    [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/userinfo.email",
    ]
)


class GoogleCalendarAuthError(Exception):
    """Raised when Google Calendar OAuth fails."""


class GoogleCalendarTokenRevoked(GoogleCalendarAuthError):
    """Refresh token permanently revoked (invalid_grant)."""


class GoogleCalendarTransientError(GoogleCalendarAuthError):
    """Transient failure (network, rate limit, 5xx)."""


def get_authorization_url(state: str) -> str:
    """Build the Google OAuth URL for Calendar access."""
    params = {
        "client_id": Config.GOOGLE_CALENDAR_CLIENT_ID,
        "redirect_uri": Config.GOOGLE_CALENDAR_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_CALENDAR_SCOPES,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_code_for_tokens(code: str) -> dict[str, Any]:
    """Exchange authorization code for tokens."""
    data = {
        "client_id": Config.GOOGLE_CALENDAR_CLIENT_ID,
        "client_secret": Config.GOOGLE_CALENDAR_CLIENT_SECRET,
        "code": code,
        "redirect_uri": Config.GOOGLE_CALENDAR_REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    try:
        response = requests.post(
            Config.GOOGLE_OAUTH_TOKEN_URL,
            data=data,
            timeout=Config.GOOGLE_CALENDAR_API_TIMEOUT,
        )
    except requests.RequestException as exc:  # pragma: no cover - network failure
        logger.error("Google token exchange failed", extra={"error": str(exc)}, exc_info=True)
        raise GoogleCalendarAuthError("Failed to connect to Google") from exc

    if response.status_code != 200:
        logger.warning(
            "Google token exchange returned error",
            extra={"status_code": response.status_code, "body": response.text},
        )
        raise GoogleCalendarAuthError("Failed to exchange authorization code for tokens")

    token_data: dict[str, Any] = response.json()
    if "access_token" not in token_data:
        logger.error("Google token response missing access_token", extra={"body": token_data})
        raise GoogleCalendarAuthError("No access token returned by Google")

    return token_data


def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    """Refresh Google Calendar access token."""
    data = {
        "client_id": Config.GOOGLE_CALENDAR_CLIENT_ID,
        "client_secret": Config.GOOGLE_CALENDAR_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    try:
        response = requests.post(
            Config.GOOGLE_OAUTH_TOKEN_URL,
            data=data,
            timeout=Config.GOOGLE_CALENDAR_API_TIMEOUT,
        )
    except requests.RequestException as exc:  # pragma: no cover - network failure
        logger.error("Google token refresh failed", extra={"error": str(exc)}, exc_info=True)
        raise GoogleCalendarTransientError("Failed to connect to Google for token refresh") from exc

    if response.status_code != 200:
        # Parse Google's error response to distinguish permanent vs transient failures
        error_code = ""
        try:
            error_body = response.json()
            error_code = error_body.get("error", "")
        except Exception:
            error_body = response.text

        logger.warning(
            "Google token refresh returned error",
            extra={
                "status_code": response.status_code,
                "error_code": error_code,
                "body": response.text,
            },
        )

        if error_code == "invalid_grant":
            raise GoogleCalendarTokenRevoked(
                "Google refresh token has been revoked or expired. User must reconnect."
            )

        if response.status_code >= 500:
            raise GoogleCalendarTransientError(
                f"Google server error ({response.status_code}) during token refresh"
            )

        raise GoogleCalendarAuthError("Failed to refresh Google access token")

    token_data: dict[str, Any] = response.json()
    if "access_token" not in token_data:
        logger.error("Google refresh response missing access_token", extra={"body": token_data})
        raise GoogleCalendarAuthError("No access token returned during refresh")

    # Refresh responses typically do not include refresh_token; preserve existing
    token_data.setdefault("refresh_token", refresh_token)
    return token_data


def get_user_info(access_token: str) -> dict[str, Any]:
    """Fetch the Google user profile info (email)."""
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(
            Config.GOOGLE_USERINFO_URL,
            headers=headers,
            timeout=Config.GOOGLE_CALENDAR_API_TIMEOUT,
        )
    except requests.RequestException as exc:  # pragma: no cover - network failure
        logger.error("Google userinfo request failed", extra={"error": str(exc)}, exc_info=True)
        raise GoogleCalendarAuthError("Failed to fetch Google profile") from exc

    if response.status_code != 200:
        logger.warning(
            "Google userinfo returned error",
            extra={"status_code": response.status_code, "body": response.text},
        )
        raise GoogleCalendarAuthError("Failed to fetch Google profile")

    data: dict[str, Any] = response.json()
    return data


def compute_token_expiry(expires_in: Any) -> datetime:
    """Convert Google's expires_in to an absolute expiry, refreshing early."""
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        seconds = 3600
    # Subtract one minute to refresh proactively
    seconds = max(60, seconds - 60)
    return datetime.now() + timedelta(seconds=seconds)


def get_valid_access_token(user_id: str) -> str | None:
    """Return a valid calendar access token for the user, refreshing if needed.

    Shared by the calendar routes and the agent tool (previously two divergent
    copies of this logic).

    Returns None when calendar is not connected or no refresh token exists.
    Raises GoogleCalendarTokenRevoked when the refresh token is permanently
    invalid and GoogleCalendarTransientError on transient failures (after one
    retry).

    Concurrency (R2): with multiple gunicorn workers two requests can refresh
    simultaneously. Refreshed tokens are stored with a compare-and-swap on the
    refresh token that was actually used - the loser's access token is still
    valid to RETURN, but storing it would overwrite the winner's (possibly
    rotated) refresh token with a stale one.
    """
    from src.db.models import db

    user = db.get_user_by_id(user_id)
    if not user or not user.google_calendar_access_token:
        return None

    # Token still comfortably valid (refresh within 10 minutes of expiry)
    expires_at = user.google_calendar_token_expires_at
    if expires_at and expires_at > datetime.now() + timedelta(minutes=10):
        return str(user.google_calendar_access_token)

    refresh_token = user.google_calendar_refresh_token
    if not refresh_token:
        logger.warning(
            "Calendar token expiring and no refresh token available",
            extra={"user_id": user_id},
        )
        return None

    refreshed: dict[str, Any] | None = None
    for attempt in range(2):
        try:
            refreshed = refresh_access_token(refresh_token)
            break
        except GoogleCalendarTransientError as e:
            if attempt == 0:
                logger.info(
                    "Transient error refreshing calendar token, retrying",
                    extra={"user_id": user_id, "error": str(e)},
                )
                continue
            logger.warning(
                "Transient error refreshing calendar token after retry",
                extra={"user_id": user_id, "error": str(e)},
            )
            raise

    if refreshed is None:  # pragma: no cover - loop always breaks or raises
        return None

    access_token: str = refreshed["access_token"]
    new_refresh = refreshed.get("refresh_token", refresh_token)
    new_expires = compute_token_expiry(refreshed.get("expires_in"))

    stored = db.refresh_user_google_calendar_tokens(
        user_id,
        used_refresh_token=refresh_token,
        access_token=access_token,
        refresh_token=new_refresh,
        expires_at=new_expires,
    )
    if not stored:
        # Another worker refreshed concurrently and already stored newer
        # tokens - ours are still valid to use for this request
        logger.info(
            "Concurrent calendar token refresh detected - keeping the other writer's tokens",
            extra={"user_id": user_id},
        )

    return access_token
