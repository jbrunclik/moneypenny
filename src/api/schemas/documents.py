"""Saved-document (document memory) schemas."""

from __future__ import annotations

from pydantic import Field

from src.api.schemas.base import ResponseModel, Timestamp


class SavedDocumentResponse(ResponseModel):
    """One saved document (its metadata; the file is a separate download)."""

    id: str
    title: str
    summary: str = Field(description="What the document contains")
    use_for: str = Field(description="When the assistant should open it")
    filename: str
    mime_type: str
    size_bytes: int
    created_at: Timestamp
    valid_until: str | None = Field(
        default=None, description="Last local day the document holds (YYYY-MM-DD)"
    )
    deleted_at: Timestamp | None = None
    last_opened_at: Timestamp | None = None
    source_conversation_id: str | None = None


class DocumentsResponse(ResponseModel):
    """The user's saved documents, the recently deleted ones and the caps."""

    documents: list[SavedDocumentResponse]
    deleted: list[SavedDocumentResponse]
    limit: int = Field(description="Maximum saved documents per user")
    bytes_used: int = Field(description="Bytes stored, deleted documents included until purged")
    bytes_limit: int = Field(description="Maximum bytes stored per user")
