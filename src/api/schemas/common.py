"""Common response components (errors, status)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from src.api.schemas.base import ResponseModel


class ErrorDetail(ResponseModel):
    """Error detail structure in error responses."""

    code: str = Field(..., description="Error code for programmatic handling")
    message: str = Field(..., description="Human-readable error message")
    retryable: bool = Field(default=False, description="Whether the request can be retried")
    details: dict[str, Any] | None = Field(default=None, description="Additional error context")


class ErrorResponse(ResponseModel):
    """Standard error response structure."""

    error: ErrorDetail


class StatusResponse(ResponseModel):
    """Simple status response for operations that don't return data."""

    status: str = Field(..., description="Operation status (e.g., 'updated', 'deleted')")
