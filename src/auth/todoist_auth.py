"""Todoist OAuth 2.0 authentication.

This module handles the OAuth flow for Todoist integration:
1. Generate authorization URL for user to authenticate with Todoist
2. Exchange authorization code for access token
"""

from typing import Any

import requests

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

TODOIST_AUTH_URL = "https://app.todoist.com/oauth/authorize"
TODOIST_TOKEN_URL = "https://api.todoist.com/oauth/access_token"
TODOIST_USER_URL = "https://api.todoist.com/api/v1/user"


class TodoistAuthError(Exception):
    """Exception raised for Todoist authentication errors."""

    pass


def get_authorization_url(state: str) -> str:
    """Generate the Todoist OAuth authorization URL.

    Args:
        state: A unique, unguessable string for CSRF protection.
               Should be stored server-side to validate the callback.

    Returns:
        The full authorization URL to redirect the user to.
    """
    # Request full read/write access for task management
    scope = "data:read_write,data:delete"

    return f"{TODOIST_AUTH_URL}?client_id={Config.TODOIST_CLIENT_ID}&scope={scope}&state={state}"


def exchange_code_for_token(code: str) -> str:
    """Exchange an authorization code for an access token.

    Args:
        code: The authorization code from Todoist's callback

    Returns:
        The access token string

    Raises:
        TodoistAuthError: If the exchange fails
    """
    logger.debug("Exchanging Todoist authorization code for token")

    try:
        response = requests.post(
            TODOIST_TOKEN_URL,
            data={
                "client_id": Config.TODOIST_CLIENT_ID,
                "client_secret": Config.TODOIST_CLIENT_SECRET,
                "code": code,
                "redirect_uri": Config.TODOIST_REDIRECT_URI,
            },
            timeout=Config.TODOIST_API_TIMEOUT,
        )

        if response.status_code != 200:
            error_msg = response.text
            logger.warning(
                "Todoist token exchange failed",
                extra={"status_code": response.status_code, "error": error_msg},
            )
            # Parse known error types
            if "bad_authorization_code" in error_msg:
                raise TodoistAuthError("Authorization code is invalid or expired")
            elif "incorrect_application_credentials" in error_msg:
                raise TodoistAuthError("Invalid Todoist application credentials")
            else:
                raise TodoistAuthError("Failed to exchange code for token")

        token_data = response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            logger.error("Todoist token response missing access_token")
            raise TodoistAuthError("No access token in response")

        logger.debug("Todoist token exchange successful")
        return str(access_token)

    except requests.RequestException as e:
        logger.error(
            "Todoist token exchange request failed", extra={"error": str(e)}, exc_info=True
        )
        raise TodoistAuthError("Failed to connect to Todoist") from e


def get_user_info(access_token: str) -> dict[str, Any]:
    """Get the authenticated user's Todoist profile.

    Uses the API v1 user endpoint.

    Args:
        access_token: The user's Todoist access token

    Returns:
        Dict with user info (email, full_name, id, etc.)

    Raises:
        TodoistAuthError: If the request fails
    """
    logger.debug("Fetching Todoist user info")

    try:
        response = requests.get(
            TODOIST_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=Config.TODOIST_API_TIMEOUT,
        )

        if response.status_code != 200:
            logger.warning(
                "Todoist user info request failed",
                extra={"status_code": response.status_code},
            )
            raise TodoistAuthError("Failed to fetch Todoist user info")

        user_data: dict[str, Any] = response.json()

        if not user_data:
            logger.error("Todoist user response empty")
            raise TodoistAuthError("No user data in response")

        return user_data

    except requests.RequestException as e:
        logger.error("Todoist user info request failed", extra={"error": str(e)}, exc_info=True)
        raise TodoistAuthError("Failed to connect to Todoist") from e


def revoke_token(access_token: str) -> bool:
    """Revoke a Todoist access token.

    Args:
        access_token: The access token to revoke

    Returns:
        True if revocation succeeded or was a no-op
    """
    try:
        response = requests.delete(
            "https://api.todoist.com/api/v1/access_tokens",
            data={
                "client_id": Config.TODOIST_CLIENT_ID,
                "client_secret": Config.TODOIST_CLIENT_SECRET,
                "access_token": access_token,
            },
            timeout=Config.TODOIST_API_TIMEOUT,
        )
        if response.status_code < 300:
            logger.debug("Todoist token revoked successfully")
            return True
        else:
            logger.warning(
                "Todoist token revocation failed",
                extra={"status_code": response.status_code},
            )
            return False
    except requests.RequestException as e:
        logger.warning("Todoist token revocation request failed", extra={"error": str(e)})
        return False
