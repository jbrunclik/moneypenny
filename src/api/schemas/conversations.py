"""Conversation CRUD, sync, pagination and search schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.api.schemas.chat import MessageResponse
from src.config import Config


class CreateConversationRequest(BaseModel):
    """Schema for POST /api/conversations."""

    model: str | None = None  # Defaults to Config.DEFAULT_MODEL in route

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str | None) -> str | None:
        """Validate model is in available models list."""
        if v is not None and v not in Config.MODELS:
            models = list(Config.MODELS.keys())
            raise ValueError(f"Invalid model. Choose from: {models}")
        return v


class UpdateConversationRequest(BaseModel):
    """Schema for PATCH /api/conversations/<conv_id>."""

    title: str | None = Field(None, min_length=1, max_length=200)
    model: str | None = None

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str | None) -> str | None:
        """Validate model is in available models list."""
        if v is not None and v not in Config.MODELS:
            models = list(Config.MODELS.keys())
            raise ValueError(f"Invalid model. Choose from: {models}")
        return v


class TruncateConversationRequest(BaseModel):
    """Schema for POST /api/conversations/<conv_id>/truncate."""

    message_id: str = Field(..., min_length=1)
    # inclusive=True deletes the target message too (edit-and-resend);
    # False deletes only what follows it
    inclusive: bool = Field(default=True)


class TruncateConversationResponse(BaseModel):
    """Number of messages removed by a truncate."""

    deleted: int


class ConversationResponse(BaseModel):
    """Conversation summary (without messages)."""

    id: str
    title: str
    model: str
    created_at: str
    updated_at: str
    message_count: int | None = None
    archived: bool | None = None
    pinned: bool | None = None
    last_message_preview: str | None = None
    deleted_at: str | None = None  # Set for conversations in the trash
    purge_at: str | None = None  # When a trashed conversation is deleted for good


class EmptyTrashResponse(BaseModel):
    """Result of emptying the trash."""

    deleted: int = Field(..., description="Number of conversations permanently deleted")


class ConversationDetailResponse(BaseModel):
    """Full conversation with messages."""

    id: str
    title: str
    model: str
    created_at: str
    updated_at: str
    is_agent: bool = False
    agent_id: str | None = None
    anonymous_mode: bool = False
    messages: list[MessageResponse]


class UpdateAnonymousModeRequest(BaseModel):
    """Request to turn anonymous mode on or off for a conversation."""

    anonymous_mode: bool = Field(
        ..., description="Whether to disable memory and integrations for this conversation"
    )


class ConversationsListResponse(BaseModel):
    """List of conversations."""

    conversations: list[ConversationResponse]


class SyncConversationResponse(BaseModel):
    """Conversation summary for sync endpoint."""

    id: str
    title: str
    model: str
    created_at: str | None = None
    updated_at: str
    message_count: int
    last_message_preview: str | None = None
    last_message_id: str | None = Field(
        default=None, description="Newest message (detects edits/deletes a count can't)"
    )
    archived: bool = False
    trashed: bool = Field(default=False, description="In the trash (deleted_at set)")
    pinned: bool = False


class SyncResponse(BaseModel):
    """Response from sync endpoint."""

    conversations: list[SyncConversationResponse]
    server_time: str = Field(..., description="ISO timestamp to use for next sync")
    is_full_sync: bool
    cursor: int = Field(
        default=0, description="Change-log position to pass as ?cursor= on the next sync"
    )
    removed_ids: list[str] = Field(
        default_factory=list, description="Conversations permanently deleted since the cursor"
    )
    has_more: bool = Field(default=False, description="More changes after cursor - sync again")


class ConversationsPaginationResponse(BaseModel):
    """Pagination info for conversations list."""

    next_cursor: str | None = Field(
        default=None, description="Cursor for fetching next page (null if no more)"
    )
    has_more: bool = Field(..., description="Whether there are more pages")
    total_count: int = Field(..., description="Total number of conversations")


class ConversationsListPaginatedResponse(BaseModel):
    """Paginated list of conversations.

    Pinned conversations ride separately: they are excluded from the
    paginated portion (pinned-first ordering would break cursor math) and
    are few by nature.
    """

    conversations: list[ConversationResponse]
    pinned_conversations: list[ConversationResponse] = Field(default_factory=list)
    pagination: ConversationsPaginationResponse


class MessagesPaginationResponse(BaseModel):
    """Pagination info for messages list."""

    older_cursor: str | None = Field(
        default=None, description="Cursor for fetching older messages (null if at oldest)"
    )
    newer_cursor: str | None = Field(
        default=None, description="Cursor for fetching newer messages (null if at newest)"
    )
    has_older: bool = Field(..., description="Whether there are older messages")
    has_newer: bool = Field(..., description="Whether there are newer messages")
    total_count: int = Field(..., description="Total number of messages in conversation")


class ConversationDetailPaginatedResponse(BaseModel):
    """Full conversation with paginated messages."""

    id: str
    title: str
    model: str
    created_at: str
    updated_at: str
    is_agent: bool = False
    agent_id: str | None = None
    has_pending_approval: bool = False  # True if agent has pending approval request
    archived: bool = False
    anonymous_mode: bool = False  # Memory and integrations disabled for this conversation
    messages: list[MessageResponse]
    message_pagination: MessagesPaginationResponse
    streaming_message_id: str | None = Field(
        default=None,
        description="Reply still being generated (e.g. on another device) - follow it via resume",
    )


class MessagesListResponse(BaseModel):
    """Paginated messages response (for dedicated messages endpoint)."""

    messages: list[MessageResponse]
    pagination: MessagesPaginationResponse


class SearchResultResponse(BaseModel):
    """Single search result."""

    conversation_id: str = Field(..., description="ID of the conversation containing the match")
    conversation_title: str = Field(..., description="Title of the conversation")
    message_id: str | None = Field(
        default=None, description="Message ID if match is in a message (null for title matches)"
    )
    message_snippet: str | None = Field(
        default=None,
        description="Snippet of matching text with [[HIGHLIGHT]] markers (null for title matches)",
    )
    match_type: Literal["conversation", "message"] = Field(
        ..., description="Whether the match is in conversation title or message content"
    )
    created_at: str | None = Field(
        default=None, description="Message timestamp (null for title matches)"
    )


class SearchResultsResponse(BaseModel):
    """Search results response."""

    results: list[SearchResultResponse] = Field(
        ..., description="List of search results ordered by relevance"
    )
    total: int = Field(..., description="Total number of matching results")
    query: str = Field(..., description="The search query that was executed")
