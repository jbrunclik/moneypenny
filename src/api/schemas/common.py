"""Shared enums and common response components (errors, status)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MessageRole(StrEnum):
    """Role of a message sender."""

    USER = "user"
    ASSISTANT = "assistant"


class ThumbnailStatus(StrEnum):
    """Status of thumbnail generation."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class PaginationDirection(StrEnum):
    """Direction for cursor-based pagination.

    Used when fetching paginated results relative to a cursor position.
    """

    OLDER = "older"
    NEWER = "newer"


class ErrorDetail(BaseModel):
    """Error detail structure in error responses."""

    code: str = Field(..., description="Error code for programmatic handling")
    message: str = Field(..., description="Human-readable error message")
    retryable: bool = Field(default=False, description="Whether the request can be retried")
    details: dict[str, Any] | None = Field(default=None, description="Additional error context")


class ErrorResponse(BaseModel):
    """Standard error response structure."""

    error: ErrorDetail


class StatusResponse(BaseModel):
    """Simple status response for operations that don't return data."""

    status: str = Field(..., description="Operation status (e.g., 'updated', 'deleted')")
