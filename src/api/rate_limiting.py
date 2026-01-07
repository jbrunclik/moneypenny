"""Rate limiting module for API endpoints.

This module provides rate limiting to protect against DoS attacks and runaway clients.
Uses Flask-Limiter with configurable storage backends (memory, Redis, Memcached).

Rate limits are applied per-user when authenticated, or per-IP for unauthenticated endpoints.
Different limits apply to different endpoint categories (auth, chat, files, etc.).
"""

from collections.abc import Callable
from typing import Any

from flask import Flask, g, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Global limiter instance (initialized in init_rate_limiting)
limiter: Limiter | None = None


def get_rate_limit_key() -> str:
    """Get the rate limit key for the current request.

    Uses user ID if authenticated (available in g.user after @require_auth),
    otherwise falls back to remote IP address.

    This provides per-user rate limiting for authenticated requests,
    preventing one user from affecting others, while still protecting
    unauthenticated endpoints by IP.
    """
    # Check if user is set (by @require_auth decorator or dev mode bypass)
    if hasattr(g, "user") and g.user:
        return f"user:{g.user.id}"

    # Fall back to IP address
    return f"ip:{get_remote_address()}"


def init_rate_limiting(app: Flask) -> Limiter | None:
    """Initialize rate limiting for the Flask app.

    Args:
        app: Flask application instance

    Returns:
        Limiter instance if enabled, None if disabled
    """
    global limiter

    if not Config.RATE_LIMITING_ENABLED:
        logger.info("Rate limiting is disabled")
        return None

    # Create limiter with configuration
    limiter = Limiter(
        key_func=get_rate_limit_key,
        app=app,
        storage_uri=Config.RATE_LIMIT_STORAGE_URI,
        # Default limits apply to all endpoints not explicitly decorated
        default_limits=[Config.RATE_LIMIT_DEFAULT],
        # Include rate limit headers in responses
        headers_enabled=True,
        # Strategy: fixed-window (simpler) vs moving-window (smoother but more memory)
        strategy="fixed-window",
    )

    # Custom error handler for rate limit exceeded
    @app.errorhandler(429)
    def rate_limit_handler(e: Exception) -> tuple[dict[str, Any], int, dict[str, str]]:
        """Handle rate limit exceeded errors with our standard error format."""
        # Get retry-after from the exception if available
        retry_after = None
        if hasattr(e, "description") and "retry after" in str(e.description).lower():
            # Try to extract retry-after seconds from the error message
            import re

            match = re.search(r"(\d+)\s*second", str(e.description))
            if match:
                retry_after = int(match.group(1))

        logger.warning(
            "Rate limit exceeded",
            extra={
                "key": get_rate_limit_key(),
                "path": request.path,
                "method": request.method,
                "retry_after": retry_after,
            },
        )

        # Use our standard error response format
        # Note: We can't use raise_rate_limited_error here because we need to return
        # a tuple, not raise an exception (Flask error handler convention)
        from src.api.errors import ErrorCode, is_retryable

        error_body = {
            "error": {
                "code": ErrorCode.RATE_LIMITED.value,
                "message": "Too many requests. Please slow down.",
                "retryable": is_retryable(ErrorCode.RATE_LIMITED),
            }
        }
        if retry_after:
            error_body["error"]["details"] = {"retry_after": retry_after}

        headers = {}
        if retry_after:
            headers["Retry-After"] = str(retry_after)

        return error_body, 429, headers

    logger.info(
        "Rate limiting initialized",
        extra={
            "storage_uri": Config.RATE_LIMIT_STORAGE_URI,
            "default_limit": Config.RATE_LIMIT_DEFAULT,
        },
    )

    return limiter


def get_limiter() -> Limiter | None:
    """Get the global limiter instance."""
    return limiter


# ============================================================================
# Rate limit decorators for different endpoint categories
# ============================================================================


def rate_limit_auth(f: Callable[..., Any]) -> Callable[..., Any]:
    """Apply authentication endpoint rate limit (stricter).

    Use for: /auth/google, password-based endpoints
    """
    if limiter is None:
        return f

    return limiter.limit(Config.RATE_LIMIT_AUTH)(f)


def rate_limit_chat(f: Callable[..., Any]) -> Callable[..., Any]:
    """Apply chat endpoint rate limit (moderate).

    Use for: /chat/batch, /chat/stream
    These are expensive operations (LLM calls) so we limit them more strictly.
    """
    if limiter is None:
        return f

    return limiter.limit(Config.RATE_LIMIT_CHAT)(f)


def rate_limit_conversations(f: Callable[..., Any]) -> Callable[..., Any]:
    """Apply conversations endpoint rate limit (generous).

    Use for: conversation CRUD, message listing
    """
    if limiter is None:
        return f

    return limiter.limit(Config.RATE_LIMIT_CONVERSATIONS)(f)


def rate_limit_files(f: Callable[..., Any]) -> Callable[..., Any]:
    """Apply file endpoint rate limit (generous but capped).

    Use for: file downloads, thumbnails
    """
    if limiter is None:
        return f

    return limiter.limit(Config.RATE_LIMIT_FILES)(f)


def exempt_from_rate_limit(f: Callable[..., Any]) -> Callable[..., Any]:
    """Exempt an endpoint from rate limiting.

    Use sparingly for endpoints that must always be available:
    - Health checks (/api/health, /api/ready)
    - Version checks (/api/version)
    """
    if limiter is None:
        return f

    return limiter.exempt(f)
