"""Standardized error response utilities for the API.

This module provides a consistent error response format across all API endpoints,
enabling the frontend to properly categorize errors and implement appropriate
handling strategies (retry, user notification, etc.).

Uses APIFlask's HTTPError for idiomatic error handling. Custom error classes
inherit from HTTPError and are properly documented in the OpenAPI spec.
"""

from enum import Enum
from typing import Any, NoReturn

from apiflask import HTTPError
from pydantic import BaseModel


class ErrorCode(str, Enum):
    """Error codes for API responses.

    These codes provide semantic meaning for frontend error handling:
    - Frontend can determine if an error is retryable
    - Frontend can show appropriate user messages
    - Frontend can implement specific handling (e.g., re-auth for AUTH errors)
    """

    # Authentication errors
    AUTH_REQUIRED = "AUTH_REQUIRED"  # Missing authentication
    AUTH_INVALID = "AUTH_INVALID"  # Invalid token/credentials
    AUTH_EXPIRED = "AUTH_EXPIRED"  # Token expired
    AUTH_FORBIDDEN = "AUTH_FORBIDDEN"  # Valid auth but not authorized

    # Validation errors
    VALIDATION_ERROR = "VALIDATION_ERROR"  # Invalid input data
    MISSING_FIELD = "MISSING_FIELD"  # Required field missing
    INVALID_FORMAT = "INVALID_FORMAT"  # Field has wrong format

    # Resource errors
    NOT_FOUND = "NOT_FOUND"  # Resource doesn't exist
    CONFLICT = "CONFLICT"  # Resource state conflict

    # Server errors (potentially retryable)
    SERVER_ERROR = "SERVER_ERROR"  # Generic server error
    TIMEOUT = "TIMEOUT"  # Request/operation timed out
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"  # Backend service down
    RATE_LIMITED = "RATE_LIMITED"  # Too many requests

    # External service errors
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"  # Third-party API failed
    LLM_ERROR = "LLM_ERROR"  # LLM/Gemini API error
    TOOL_ERROR = "TOOL_ERROR"  # Tool execution failed


# Errors that the frontend may safely retry automatically (for idempotent operations)
RETRYABLE_ERRORS = {
    ErrorCode.TIMEOUT,
    ErrorCode.SERVICE_UNAVAILABLE,
    ErrorCode.RATE_LIMITED,
    ErrorCode.SERVER_ERROR,  # May be transient
}


def is_retryable(code: ErrorCode) -> bool:
    """Check if an error code indicates a retryable error."""
    return code in RETRYABLE_ERRORS


# =============================================================================
# Pydantic schema for OpenAPI documentation
# =============================================================================


class ErrorDetail(BaseModel):
    """Error detail schema for OpenAPI documentation."""

    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """Error response schema for OpenAPI documentation."""

    error: ErrorDetail


# =============================================================================
# Custom HTTPError subclass for our error format
# =============================================================================


class APIError(HTTPError):
    """Custom HTTPError that uses our standardized error format.

    This integrates with APIFlask's error handling while maintaining
    our custom error structure with code, message, retryable, and details.
    """

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        # Build error dict with our custom structure
        error_dict: dict[str, Any] = {
            "code": code.value,
            "message": message,
            "retryable": is_retryable(code),
        }
        if details:
            error_dict["details"] = details

        # Store our custom fields in extra_data, which APIFlask includes in response
        extra_data: dict[str, Any] = {"error": error_dict}

        # Call parent with empty message since we put everything in extra_data
        # APIFlask will merge extra_data into the response body
        super().__init__(status_code=status_code, message="", extra_data=extra_data)

        # Store for potential access
        self.code = code
        self.error_message = message
        self.details = details


# =============================================================================
# Convenience functions for raising common errors
# =============================================================================


def raise_validation_error(message: str, field: str | None = None) -> NoReturn:
    """Raise a validation error (400)."""
    details = {"field": field} if field else None
    raise APIError(400, ErrorCode.VALIDATION_ERROR, message, details)


def raise_missing_field_error(field: str) -> NoReturn:
    """Raise a missing field error (400)."""
    raise APIError(
        400, ErrorCode.MISSING_FIELD, f"Missing required field: {field}", {"field": field}
    )


def raise_invalid_format_error(message: str = "Invalid format") -> NoReturn:
    """Raise an invalid format error (400)."""
    raise APIError(400, ErrorCode.INVALID_FORMAT, message)


def raise_not_found_error(resource: str = "Resource") -> NoReturn:
    """Raise a not found error (404)."""
    raise APIError(404, ErrorCode.NOT_FOUND, f"{resource} not found")


def raise_auth_required_error() -> NoReturn:
    """Raise an authentication required error (401)."""
    raise APIError(401, ErrorCode.AUTH_REQUIRED, "Authentication required")


def raise_auth_invalid_error(message: str = "Invalid credentials") -> NoReturn:
    """Raise an invalid authentication error (401)."""
    raise APIError(401, ErrorCode.AUTH_INVALID, message)


def raise_auth_expired_error(message: str = "Token expired") -> NoReturn:
    """Raise an expired authentication error (401).

    This is distinct from AUTH_INVALID to allow the frontend to prompt
    re-authentication rather than treating it as a credentials error.
    """
    raise APIError(401, ErrorCode.AUTH_EXPIRED, message)


def raise_auth_forbidden_error(message: str = "Access denied") -> NoReturn:
    """Raise a forbidden error (403)."""
    raise APIError(403, ErrorCode.AUTH_FORBIDDEN, message)


def raise_timeout_error(
    message: str = "Request timed out. Please try again.",
    timeout_seconds: int | None = None,
) -> NoReturn:
    """Raise a timeout error (504)."""
    details = {"timeout_seconds": timeout_seconds} if timeout_seconds else None
    raise APIError(504, ErrorCode.TIMEOUT, message, details)


def raise_server_error(
    message: str = "An unexpected error occurred. Please try again.",
) -> NoReturn:
    """Raise a generic server error (500).

    Note: Never expose internal error details to users. Log them server-side instead.
    """
    raise APIError(500, ErrorCode.SERVER_ERROR, message)


def raise_service_unavailable_error(
    message: str = "Service temporarily unavailable. Please try again later.",
) -> NoReturn:
    """Raise a service unavailable error (503)."""
    raise APIError(503, ErrorCode.SERVICE_UNAVAILABLE, message)


def raise_rate_limited_error(
    message: str = "Too many requests. Please slow down.",
    retry_after: int | None = None,
) -> NoReturn:
    """Raise a rate limited error (429)."""
    details = {"retry_after": retry_after} if retry_after else None
    raise APIError(429, ErrorCode.RATE_LIMITED, message, details)


def raise_llm_error(message: str = "AI service error. Please try again.") -> NoReturn:
    """Raise an LLM/Gemini error (502)."""
    raise APIError(502, ErrorCode.LLM_ERROR, message)


def raise_tool_error(
    message: str = "Tool execution failed.",
    tool_name: str | None = None,
) -> NoReturn:
    """Raise a tool execution error (500)."""
    details = {"tool": tool_name} if tool_name else None
    raise APIError(500, ErrorCode.TOOL_ERROR, message, details)


def raise_external_service_error(
    message: str = "External service error. Please try again.",
    service: str | None = None,
) -> NoReturn:
    """Raise an external service error (502)."""
    details = {"service": service} if service else None
    raise APIError(502, ErrorCode.EXTERNAL_SERVICE_ERROR, message, details)


def raise_invalid_json_error() -> NoReturn:
    """Raise an invalid JSON error (400)."""
    raise APIError(400, ErrorCode.INVALID_FORMAT, "Invalid JSON in request body")


# =============================================================================
# Legacy function-based API (returns values instead of raising)
# Keep for backward compatibility with existing code
# =============================================================================


def create_error_response(
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a standardized error response dict.

    Args:
        code: Error code enum value
        message: Human-readable error message (safe to show to users)
        details: Optional additional details (e.g., field name for validation errors)

    Returns:
        Dict with standardized error structure:
        {
            "error": {
                "code": "ERROR_CODE",
                "message": "Human-readable message",
                "retryable": true/false,
                "details": {...}  # optional
            }
        }
    """
    error_data: dict[str, Any] = {
        "code": code.value,
        "message": message,
        "retryable": is_retryable(code),
    }

    if details:
        error_data["details"] = details

    return {"error": error_data}


def validation_error_dict(message: str, field: str | None = None) -> tuple[dict[str, Any], int]:
    """Create a validation error dict and status code (for use outside Flask context)."""
    details = {"field": field} if field else None
    return create_error_response(ErrorCode.VALIDATION_ERROR, message, details), 400
