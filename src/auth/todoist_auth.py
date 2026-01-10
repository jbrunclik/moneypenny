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

TODOIST_AUTH_URL = "https://todoist.com/oauth/authorize"
TODOIST_TOKEN_URL = "https://todoist.com/oauth/access_token"
TODOIST_SYNC_URL = "https://api.todoist.com/sync/v9/sync"


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

    Uses the Sync API since the REST API v2 doesn't have a user endpoint.

    Args:
        access_token: The user's Todoist access token

    Returns:
        Dict with user info (email, full_name, id, etc.)

    Raises:
        TodoistAuthError: If the request fails
    """
    logger.debug("Fetching Todoist user info via Sync API")

    try:
        response = requests.post(
            TODOIST_SYNC_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            data={
                "sync_token": "*",
                "resource_types": '["user"]',
            },
            timeout=Config.TODOIST_API_TIMEOUT,
        )

        if response.status_code != 200:
            logger.warning(
                "Todoist user info request failed",
                extra={"status_code": response.status_code},
            )
            raise TodoistAuthError("Failed to fetch Todoist user info")

        sync_data = response.json()
        user_data = sync_data.get("user")

        if not user_data:
            logger.error("Todoist sync response missing user data")
            raise TodoistAuthError("No user data in response")

        result: dict[str, Any] = user_data
        return result

    except requests.RequestException as e:
        logger.error("Todoist user info request failed", extra={"error": str(e)}, exc_info=True)
        raise TodoistAuthError("Failed to connect to Todoist") from e


def revoke_token(access_token: str) -> bool:
    """Revoke a Todoist access token.

    Note: Todoist doesn't have a token revocation endpoint.
    This function is a placeholder that returns True - the token
    will be removed from our database on disconnect.

    Args:
        access_token: The access token to revoke (unused)

    Returns:
        Always True
    """
    # Todoist doesn't support token revocation via API
    # The user must revoke access manually in Todoist settings
    logger.debug("Todoist token revocation requested (no-op - Todoist doesn't support revocation)")
    return True
