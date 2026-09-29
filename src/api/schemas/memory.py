"""User memory schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryResponse(BaseModel):
    """Single memory entry."""

    id: str
    content: str
    category: str | None = None
    created_at: str
    updated_at: str
    protected: bool = False
    source_conversation_id: str | None = None
    deleted_at: str | None = None


class MemoriesListResponse(BaseModel):
    """List of memories."""

    memories: list[MemoryResponse]
    # Served from config so the UI does not keep its own copy of the cap
    limit: int = Field(default=0, description="Maximum memories this user can store")


class UpdateMemoryProtectionRequest(BaseModel):
    """Request to protect or unprotect a memory."""

    protected: bool = Field(..., description="Whether the memory is exempt from auto-deletion")
