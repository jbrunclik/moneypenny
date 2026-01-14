"""Authentication routes: Google Sign-In, JWT token management.

This module handles user authentication via Google OAuth and JWT token operations.
"""

from typing import Any

from apiflask import APIBlueprint

from src.api.errors import (
    raise_auth_forbidden_error,
    raise_auth_invalid_error,
    raise_validation_error,
)
from src.api.rate_limiting import rate_limit_auth
from src.api.schemas import (
    AuthResponse,
    ClientIdResponse,
    GoogleAuthRequest,
    TokenRefreshResponse,
    UserContainerResponse,
)
from src.api.validation import validate_request
from src.auth.google_auth import GoogleAuthError, is_email_allowed, verify_google_id_token
from src.auth.jwt_auth import create_token, require_auth
from src.config import Config
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)

auth = APIBlueprint("auth", __name__, url_prefix="/auth", tag="Auth")


# ============================================================================
# Auth Routes
# ============================================================================


@auth.route("/google", methods=["POST"])
@auth.output(AuthResponse, status_code=200)
@auth.doc(responses=[400, 401, 403, 429])
@rate_limit_auth
@validate_request(GoogleAuthRequest)
def google_auth(data: GoogleAuthRequest) -> tuple[dict[str, Any], int]:
    """Authenticate with Google ID token from Sign In with Google."""
    logger.info("Google authentication request")
    if Config.is_development():
        logger.warning("Authentication attempted in development mode")
        raise_validation_error("Authentication disabled in local mode")

    id_token = data.credential

    try:
        logger.debug("Verifying Google ID token")
        user_info = verify_google_id_token(id_token)
        email = user_info.get("email", "")
        logger.debug("Google token verified", extra={"email": email})
    except GoogleAuthError as e:
        logger.warning("Google token verification failed", extra={"error": str(e)})
        raise_auth_invalid_error(str(e))

    if not is_email_allowed(email):
        logger.warning("Email not in whitelist", extra={"email": email})
        raise_auth_forbidden_error("Email not authorized")

    # Create or get user
    logger.debug("Getting or creating user", extra={"email": email})
    user = db.get_or_create_user(
        email=email,
        name=user_info.get("name", email),
        picture=user_info.get("picture"),
    )

    # Generate JWT token
    token = create_token(user)
    logger.info("Google authentication successful", extra={"user_id": user.id, "email": email})

    return {
        "token": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "picture": user.picture,
        },
    }, 200


@auth.route("/client-id", methods=["GET"])
@auth.output(ClientIdResponse)
def get_client_id() -> dict[str, str]:
    """Return Google Client ID for frontend initialization."""
    return {"client_id": Config.GOOGLE_CLIENT_ID}


@auth.route("/me")
@auth.output(UserContainerResponse)
@require_auth
def me(user: User) -> dict[str, dict[str, str | None]]:
    """Get current user info."""
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "picture": user.picture,
        }
    }


@auth.route("/refresh", methods=["POST"])
@auth.output(TokenRefreshResponse)
@require_auth
def refresh_token(user: User) -> dict[str, str]:
    """Refresh the JWT token.

    Returns a new token with extended expiration.
    The old token remains valid until its original expiration.
    """
    logger.info("Token refresh requested", extra={"user_id": user.id})
    token = create_token(user)
    logger.info("Token refreshed successfully", extra={"user_id": user.id})

    return {"token": token}
