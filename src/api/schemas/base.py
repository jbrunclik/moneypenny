"""Base classes for API schemas: the direction data flows decides the spec.

The OpenAPI spec is the source of the frontend's types, and the two directions
need opposite answers for a field with a default:

- a request field with a default may be left out by the client (optional);
- a response field with a default is always sent by the server (required).

Pydantic's schema gives the first answer. The server serializes every field
of a response (APIFlask dumps the whole model), so a response model lists all
of its properties as required. (Pydantic's json_schema_mode_override would
say the same but breaks on a nested model referenced twice - pydantic 2.14.)
Every schema inherits one of the two; a test checks it.
"""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

# An instant the server sends: ISO 8601 with an explicit UTC offset, always
# YYYY-MM-DDTHH:MM:SS.ffffff+00:00 (src/utils/clock.py to_api)
Timestamp = Annotated[str, Field(json_schema_extra={"format": "date-time"})]


def _all_properties_required(schema: dict[str, Any]) -> None:
    if schema.get("properties"):
        schema["required"] = list(schema["properties"])


class RequestModel(BaseModel):
    """A body the client sends: a field with a default may be omitted."""


class QueryModel(RequestModel):
    """A query string the client sends (validated by @validate_query).

    Every value arrives as a string. The parse_* helpers below keep the
    routes' long-standing reading of them: a blank or unparsable number falls
    back to its default instead of failing the request.
    """


def parse_int(
    value: Any, default: int | None, low: int | None = None, high: int | None = None
) -> Any:
    """Read a query-string int: blank or unparsable -> default, then clamp to [low, high]."""
    if not isinstance(value, str):
        return value
    try:
        number = int(value)
    except ValueError:
        return default
    if low is not None:
        number = max(low, number)
    if high is not None:
        number = min(number, high)
    return number


def parse_flag(value: Any) -> Any:
    """Read a query-string boolean: "true" (any case) is true, anything else false."""
    if isinstance(value, str):
        return value.lower() == "true"
    return value


class ResponseModel(BaseModel):
    """A body the server sends: every field is present, defaults included."""

    model_config = ConfigDict(json_schema_extra=_all_properties_required)
