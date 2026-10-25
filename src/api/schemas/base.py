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

from typing import Any

from pydantic import BaseModel, ConfigDict


def _all_properties_required(schema: dict[str, Any]) -> None:
    if schema.get("properties"):
        schema["required"] = list(schema["properties"])


class RequestModel(BaseModel):
    """A body the client sends: a field with a default may be omitted."""


class ResponseModel(BaseModel):
    """A body the server sends: every field is present, defaults included."""

    model_config = ConfigDict(json_schema_extra=_all_properties_required)
