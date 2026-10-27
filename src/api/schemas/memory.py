"""User memory schemas."""

from __future__ import annotations

from pydantic import Field

from src.api.schemas.base import RequestModel, ResponseModel, Timestamp


class MemoryResponse(ResponseModel):
    """Single memory entry."""

    id: str
    content: str
    category: str | None = None
    created_at: Timestamp
    updated_at: Timestamp
    protected: bool = False
    source_conversation_id: str | None = None
    deleted_at: Timestamp | None = None


class MemoriesListResponse(ResponseModel):
    """List of memories."""

    memories: list[MemoryResponse]
    # Served from config so the UI does not keep its own copy of the cap
    limit: int = Field(default=0, description="Maximum memories this user can store")


class UpdateMemoryProtectionRequest(RequestModel):
    """Request to protect or unprotect a memory."""

    protected: bool = Field(..., description="Whether the memory is exempt from auto-deletion")
