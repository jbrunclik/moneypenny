from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from functools import wraps
from typing import Any

import jwt
from flask import Request, g, request

from src.api.errors import (
    raise_auth_expired_error,
    raise_auth_invalid_error,
    raise_auth_required_error,
)
from src.config import Config
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)


class TokenStatus(Enum):
    """Status codes for token validation results."""

    VALID = "valid"
    EXPIRED = "expired"
    INVALID = "invalid"


@dataclass
class TokenResult:
    """Result of token validation."""

    status: TokenStatus
    payload: dict[str, Any] | None = None
    error: str | None = None


def create_token(user: User) -> str:
    """Create a JWT token for a user."""
    logger.debug("Creating JWT token", extra={"user_id": user.id, "email": user.email})
    payload = {
        "sub": user.id,
        "email": user.email,
        "name": user.name,
        "exp": datetime.now(UTC) + timedelta(seconds=Config.JWT_EXPIRATION_SECONDS),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm=Config.JWT_ALGORITHM)
    logger.debug("JWT token created", extra={"user_id": user.id})
    return token


def decode_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT token.

    Returns the payload dict if valid, None otherwise.
    For detailed status information, use decode_token_with_status() instead.
    """
    result = decode_token_with_status(token)
    return result.payload if result.status == TokenStatus.VALID else None


def decode_token_with_status(token: str) -> TokenResult:
    """Decode and validate a JWT token with detailed status.

    Returns a TokenResult with status indicating whether the token is
    valid, expired, or invalid, along with the payload or error message.
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token, Config.JWT_SECRET_KEY, algorithms=[Config.JWT_ALGORITHM]
        )
        logger.debug("JWT token decoded successfully", extra={"user_id": payload.get("sub")})
        return TokenResult(status=TokenStatus.VALID, payload=payload)
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expired")
        return TokenResult(status=TokenStatus.EXPIRED, error="Token has expired")
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid JWT token", extra={"error": str(e)})
        return TokenResult(status=TokenStatus.INVALID, error=str(e))


def get_token_from_request(req: Request) -> str | None:
    """Extract JWT token from Authorization header."""
    auth_header = req.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


def get_current_user() -> User | None:
    """Get the current authenticated user from the request context."""
    return getattr(g, "current_user", None)


def require_auth[F: Callable[..., Any]](f: F) -> F:
    """Decorator to require authentication for a route.

    Injects the authenticated User as the first argument to the decorated function.
    The function should have a signature like: def my_route(user: User, ...) -> ...

    Returns standardized error responses:
    - AUTH_REQUIRED (401): No token provided
    - AUTH_EXPIRED (401): Token has expired (prompts re-auth on frontend)
    - AUTH_INVALID (401): Token is malformed or invalid
    - NOT_FOUND (401): User associated with token no longer exists
    """

    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        # Skip auth in development mode and E2E testing (not unit/integration tests)
        if Config.should_bypass_auth():
            # Create a default local user
            local_user = db.get_or_create_user(
                email="local@localhost",
                name="Local User",
            )
            g.current_user = local_user
            logger.debug("Auth bypassed", extra={"mode": Config.FLASK_ENV})
            return f(local_user, *args, **kwargs)

        token = get_token_from_request(request)
        if not token:
            logger.warning("Missing authentication token", extra={"path": request.path})
            raise_auth_required_error()

        # Use decode_token_with_status to distinguish expired from invalid
        result = decode_token_with_status(token)

        if result.status == TokenStatus.EXPIRED:
            logger.warning("Token expired", extra={"path": request.path})
            raise_auth_expired_error("Your session has expired. Please sign in again.")

        if result.status == TokenStatus.INVALID:
            logger.warning("Invalid token", extra={"path": request.path, "error": result.error})
            raise_auth_invalid_error("Invalid authentication token")

        # Token is valid, extract user info
        payload = result.payload
        assert payload is not None  # Guaranteed by VALID status

        user_id = payload.get("sub")
        if not user_id:
            logger.warning("Invalid token payload - missing sub", extra={"path": request.path})
            raise_auth_invalid_error("Invalid token payload")

        user = db.get_user_by_id(user_id)
        if not user:
            logger.warning(
                "User not found for token", extra={"user_id": user_id, "path": request.path}
            )
            # Use 401 for user not found (token is valid but user was deleted)
            raise_auth_invalid_error("User account not found")

        g.current_user = user
        logger.debug("Authentication successful", extra={"user_id": user_id, "path": request.path})
        return f(user, *args, **kwargs)

    return decorated  # type: ignore[return-value]
