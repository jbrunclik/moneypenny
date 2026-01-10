"""Google Calendar OAuth helpers."""

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
        raise GoogleCalendarAuthError("Failed to refresh Google access token") from exc

    if response.status_code != 200:
        logger.warning(
            "Google token refresh returned error",
            extra={"status_code": response.status_code, "body": response.text},
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
