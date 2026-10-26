"""Common response components."""

from __future__ import annotations

from pydantic import Field

from src.api.schemas.base import ResponseModel


class StatusResponse(ResponseModel):
    """Simple status response for operations that don't return data."""

    status: str = Field(..., description="Operation status (e.g., 'updated', 'deleted')")
