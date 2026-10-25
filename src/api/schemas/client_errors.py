"""Browser error report schema."""

from enum import StrEnum

from pydantic import Field

from src.api.schemas.base import RequestModel


class ClientErrorKind(StrEnum):
    """How the browser caught the error."""

    ERROR = "error"  # window "error": an uncaught exception
    UNHANDLED_REJECTION = "unhandled_rejection"
    LOGGED = "logged"  # handled, but logged at error level


class ClientErrorReport(RequestModel):
    """One error from the browser. Long text is accepted and cut server-side."""

    kind: ClientErrorKind
    message: str = Field(..., min_length=1, max_length=5000)
    stack: str | None = Field(None, max_length=20000)
    path: str | None = Field(None, max_length=2000, description="Route path, no query")
    app_version: str | None = Field(None, max_length=64)
