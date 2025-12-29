"""Request validation utilities using Pydantic.

This module provides a decorator for validating Flask request bodies against
Pydantic schemas, converting validation errors to the standardized error
format used throughout the API.
"""

from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import request
from pydantic import BaseModel, ValidationError

from src.api.errors import invalid_json_error, validation_error
from src.api.utils import get_request_json
from src.utils.logging import get_logger

logger = get_logger(__name__)


def pydantic_to_error_response(
    error: ValidationError,
) -> tuple[dict[str, Any], int]:
    """Convert Pydantic ValidationError to standardized API error response.

    Converts Pydantic's error format to the existing error format used by
    validation_error() in src/api/errors.py.

    Pydantic error format:
    {
        "type": "value_error",
        "loc": ("field_name",),
        "msg": "Human-readable message",
        "input": <invalid_value>,
        "ctx": {...}  # optional context
    }

    Our error format:
    {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Human-readable message",
            "retryable": false,
            "details": {"field": "field_name"}
        }
    }
    """
    # Get first error (most relevant)
    first_error = error.errors()[0]

    # Extract field name from location tuple
    loc = first_error.get("loc", ())
    field = ".".join(str(x) for x in loc) if loc else None

    # Get the human-readable message
    message = first_error.get("msg", "Invalid input")

    # If the message starts with "Value error, " (from custom validators), clean it
    if message.startswith("Value error, "):
        message = message[13:]  # Remove "Value error, " prefix

    logger.debug(
        "Pydantic validation failed",
        extra={
            "field": field,
            "error_message": message,
            "error_count": len(error.errors()),
        },
    )

    return validation_error(message, field=field)


def validate_request[T: BaseModel](
    schema_class: type[T],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that validates request JSON against a Pydantic schema.

    Usage:
        @api.route("/endpoint", methods=["POST"])
        @require_auth
        @validate_request(MyRequestSchema)
        def my_endpoint(user: User, data: MyRequestSchema) -> ...:
            # user is injected by @require_auth
            # data is the validated Pydantic model instance
            ...

    The decorator:
    1. Parses request JSON using get_request_json()
    2. Validates against the schema
    3. On success: inserts validated model after injected args (e.g., user from @require_auth)
    4. On failure: returns standardized error response

    Note: This decorator should be placed AFTER @require_auth so that
    auth errors are returned before validation is attempted. The validated
    data is inserted after any args injected by outer decorators (like user).
    """

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Parse JSON from request
            data = get_request_json(request)
            if data is None:
                return invalid_json_error()

            # Validate against schema
            try:
                validated = schema_class.model_validate(data)
            except ValidationError as e:
                return pydantic_to_error_response(e)

            # Insert validated data after any injected args (like user from @require_auth)
            # but before URL parameters (which come via kwargs from Flask)
            return f(*args, validated, **kwargs)

        return wrapper

    return decorator
