"""Google Identity Services (GIS) authentication.

This module validates Google ID tokens from the client-side Sign In with Google flow.
No client secret is needed - just a Client ID.
"""

from typing import Any

import requests

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


class GoogleAuthError(Exception):
    """Exception raised for Google authentication errors."""

    pass


def verify_google_id_token(id_token: str) -> dict[str, Any]:
    """Verify a Google ID token and return the user info.

    Args:
        id_token: The ID token from Google Sign-In

    Returns:
        User info dict with email, name, picture, etc.

    Raises:
        GoogleAuthError: If token is invalid or verification fails
    """
    logger.debug("Verifying Google ID token")
    # Verify token with Google's tokeninfo endpoint
    try:
        from src.config import Config

        response = requests.get(
            GOOGLE_TOKENINFO_URL,
            params={"id_token": id_token},
            timeout=Config.GOOGLE_AUTH_TIMEOUT,
        )

        if response.status_code != 200:
            logger.warning(
                "Google token verification failed", extra={"status_code": response.status_code}
            )
            raise GoogleAuthError("Invalid ID token")

        token_info = response.json()

        # Verify the token was issued for our app
        if token_info.get("aud") != Config.GOOGLE_CLIENT_ID:
            logger.warning(
                "Token audience mismatch",
                extra={"aud": token_info.get("aud"), "expected": Config.GOOGLE_CLIENT_ID},
            )
            raise GoogleAuthError("Token was not issued for this application")

        # Check token is not expired (Google's endpoint does this, but double-check)
        if "email" not in token_info:
            logger.warning("Token missing email")
            raise GoogleAuthError("Token does not contain email")

        email = token_info.get("email", "")
        logger.debug("Google token verified", extra={"email": email})
        return {
            "email": email,
            "name": token_info.get("name", email),
            "picture": token_info.get("picture"),
            "email_verified": token_info.get("email_verified") == "true",
        }
    except requests.RequestException as e:
        logger.error(  # noqa: G201
            "Google token verification request failed", extra={"error": str(e)}, exc_info=True
        )
        raise GoogleAuthError("Failed to verify token with Google") from e


def is_email_allowed(email: str) -> bool:
    """Check if the email is in the allowed list."""
    return email.lower() in [e.lower() for e in Config.ALLOWED_EMAILS]
