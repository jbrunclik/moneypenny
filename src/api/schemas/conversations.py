"""Conversation CRUD, sync, pagination and search schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator

from src.api.schemas.base import QueryModel, RequestModel, ResponseModel, parse_flag, parse_int
from src.api.schemas.chat import MessageResponse
from src.config import Config
from src.enums import PaginationDirection


class CreateConversationRequest(RequestModel):
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


class UpdateConversationRequest(RequestModel):
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


class TruncateConversationRequest(RequestModel):
    """Schema for POST /api/conversations/<conv_id>/truncate."""

    message_id: str = Field(..., min_length=1)
    # inclusive=True deletes the target message too (edit-and-resend);
    # False deletes only what follows it
    inclusive: bool = Field(default=True)


class TruncateConversationResponse(ResponseModel):
    """Number of messages removed by a truncate."""

    deleted: int


class ConversationResponse(ResponseModel):
    """Conversation summary (without messages)."""

    id: str
    title: str
    model: str
    created_at: str
    updated_at: str
    message_count: int | None = None
    read_count: int | None = Field(
        default=None, description="Messages already shown on any device (unread badge)"
    )
    archived: bool | None = None
    pinned: bool | None = None
    last_message_preview: str | None = None
    deleted_at: str | None = None  # Set for conversations in the trash
    purge_at: str | None = None  # When a trashed conversation is deleted for good


class EmptyTrashResponse(ResponseModel):
    """Result of emptying the trash."""

    deleted: int = Field(..., description="Number of conversations permanently deleted")


class BulkTrashRequest(RequestModel):
    """Move many conversations to the trash: hand-picked ids, or every
    unpinned main-list chat (all) minus exclude_ids plus ids."""

    all: bool = Field(default=False, description="Every unpinned main-list chat")
    ids: list[str] = Field(
        default_factory=list,
        max_length=Config.CONVERSATIONS_BULK_MAX_IDS,
        description="Chats to trash; with all, extra chats (pinned ones picked by hand)",
    )
    exclude_ids: list[str] = Field(
        default_factory=list,
        max_length=Config.CONVERSATIONS_BULK_MAX_IDS,
        description="With all: chats to keep",
    )
    created_before: datetime | None = Field(
        default=None, description="With all: only chats created before this moment"
    )

    @model_validator(mode="after")
    def validate_shape(self) -> BulkTrashRequest:
        """ids alone, or all with created_before."""
        if self.all:
            if self.created_before is None:
                raise ValueError("created_before is required with all")
            return self
        if not self.ids:
            raise ValueError("ids or all is required")
        if self.exclude_ids or self.created_before is not None:
            raise ValueError("exclude_ids and created_before need all")
        return self


class BulkTrashResponse(ResponseModel):
    """Result of a bulk trash."""

    trashed_ids: list[str] = Field(..., description="Conversations this call moved to the trash")


class BulkRestoreRequest(RequestModel):
    """Restore many conversations from the trash (Undo of a bulk delete)."""

    ids: list[str] = Field(..., min_length=1, max_length=Config.CONVERSATIONS_BULK_MAX_IDS)


class BulkRestoreResponse(ResponseModel):
    """Result of a bulk restore."""

    restored_ids: list[str] = Field(..., description="Conversations this call restored")


class ConversationDetailResponse(ResponseModel):
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


class MarkReadRequest(RequestModel):
    """A device has shown the conversation up to this many messages."""

    message_count: int = Field(..., ge=0, description="Messages shown (server clamps)")


class UpdateAnonymousModeRequest(RequestModel):
    """Request to turn anonymous mode on or off for a conversation."""

    anonymous_mode: bool = Field(
        ..., description="Whether to disable memory and integrations for this conversation"
    )


class ConversationsListResponse(ResponseModel):
    """List of conversations."""

    conversations: list[ConversationResponse]


class SyncConversationResponse(ResponseModel):
    """Conversation summary for sync endpoint."""

    id: str
    title: str
    model: str
    created_at: str | None = None
    updated_at: str
    message_count: int
    read_count: int = Field(default=0, description="Messages already shown on any device")
    last_message_preview: str | None = None
    last_message_id: str | None = Field(
        default=None, description="Newest message (detects edits/deletes a count can't)"
    )
    archived: bool = False
    trashed: bool = Field(default=False, description="In the trash (deleted_at set)")
    pinned: bool = False
    anonymous_mode: bool = Field(default=False, description="Memory and integrations off")


class SyncResponse(ResponseModel):
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


class ConversationsPaginationResponse(ResponseModel):
    """Pagination info for conversations list."""

    next_cursor: str | None = Field(
        default=None, description="Cursor for fetching next page (null if no more)"
    )
    has_more: bool = Field(..., description="Whether there are more pages")
    total_count: int = Field(..., description="Total number of conversations")


class ConversationsListPaginatedResponse(ResponseModel):
    """Paginated list of conversations.

    Pinned conversations ride separately: they are excluded from the
    paginated portion (pinned-first ordering would break cursor math) and
    are few by nature.
    """

    conversations: list[ConversationResponse]
    pinned_conversations: list[ConversationResponse] = Field(default_factory=list)
    pagination: ConversationsPaginationResponse


class MessagesPaginationResponse(ResponseModel):
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


class ConversationDetailPaginatedResponse(ResponseModel):
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
    lost_reply: bool = Field(
        default=False,
        description="The last turn died (its worker was killed) with nothing saved - offer a retry",
    )


class MessagesListResponse(ResponseModel):
    """Paginated messages response (for dedicated messages endpoint)."""

    messages: list[MessageResponse]
    pagination: MessagesPaginationResponse


class SearchResultResponse(ResponseModel):
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


class SearchResultsResponse(ResponseModel):
    """Search results response."""

    results: list[SearchResultResponse] = Field(
        ..., description="List of search results ordered by relevance"
    )
    total: int = Field(..., description="Total number of matching results")
    query: str = Field(..., description="The search query that was executed")


# --- Query strings (@validate_query) ---


def _parse_direction(value: Any) -> Any:
    """An unknown direction reads as the default, older."""
    if isinstance(value, str) and value not in {d.value for d in PaginationDirection}:
        return PaginationDirection.OLDER
    return value


def _check_cursor(value: str | None) -> str | None:
    """A page cursor is '{timestamp}:{id}' (src/db/models/helpers.py build_cursor)."""
    if value and ":" not in value:
        raise ValueError("Invalid cursor. Use the cursor from the previous page.")
    return value


class ConversationsPageQuery(QueryModel):
    """Query for GET /api/conversations, /conversations/archived and /conversations/trash."""

    limit: int = Field(
        default=Config.CONVERSATIONS_DEFAULT_PAGE_SIZE,
        description="Conversations per page (clamped to 1..CONVERSATIONS_MAX_PAGE_SIZE)",
    )
    cursor: str | None = Field(default=None, description="next_cursor of the previous page")

    @field_validator("limit", mode="before")
    @classmethod
    def _page_size(cls, value: Any) -> Any:
        return parse_int(
            value, Config.CONVERSATIONS_DEFAULT_PAGE_SIZE, 1, Config.CONVERSATIONS_MAX_PAGE_SIZE
        )

    _cursor = field_validator("cursor")(_check_cursor)


class ConversationDetailQuery(QueryModel):
    """Query for GET /api/conversations/<id> (its first page of messages)."""

    message_limit: int = Field(
        default=Config.MESSAGES_DEFAULT_PAGE_SIZE,
        description="Messages per page (clamped to 1..MESSAGES_MAX_PAGE_SIZE)",
    )
    message_cursor: str | None = Field(default=None, description="Cursor of an adjacent page")
    direction: PaginationDirection = PaginationDirection.OLDER

    @field_validator("message_limit", mode="before")
    @classmethod
    def _page_size(cls, value: Any) -> Any:
        return parse_int(value, Config.MESSAGES_DEFAULT_PAGE_SIZE, 1, Config.MESSAGES_MAX_PAGE_SIZE)

    _direction = field_validator("direction", mode="before")(_parse_direction)
    _cursor = field_validator("message_cursor")(_check_cursor)


class MessagesPageQuery(QueryModel):
    """Query for GET /api/conversations/<id>/messages."""

    limit: int = Field(
        default=Config.MESSAGES_DEFAULT_PAGE_SIZE,
        description="Messages per page (clamped to 1..MESSAGES_MAX_PAGE_SIZE)",
    )
    # Before cursor, so the cursor check can see it (validation follows field order)
    around_message_id: str | None = Field(
        default=None,
        description="Load the page around this message (search navigation); "
        "cursor and direction are then ignored",
    )
    cursor: str | None = Field(default=None, description="Cursor of an adjacent page")
    direction: PaginationDirection = PaginationDirection.OLDER

    @field_validator("limit", mode="before")
    @classmethod
    def _page_size(cls, value: Any) -> Any:
        return parse_int(value, Config.MESSAGES_DEFAULT_PAGE_SIZE, 1, Config.MESSAGES_MAX_PAGE_SIZE)

    _direction = field_validator("direction", mode="before")(_parse_direction)

    @field_validator("cursor")
    @classmethod
    def _cursor(cls, value: str | None, info: ValidationInfo) -> str | None:
        # around_message_id ignores the cursor, so it isn't checked then either
        return value if info.data.get("around_message_id") else _check_cursor(value)


class SyncQuery(QueryModel):
    """Query for GET /api/conversations/sync.

    since and cursor stay strings: the route parses them only when they
    decide the sync mode (full=true ignores both).
    """

    since: str | None = Field(default=None, description="ISO timestamp (legacy timestamp sync)")
    cursor: str | None = Field(default=None, description="Change-log cursor from the last sync")
    full: bool = Field(default=False, description="Return every conversation")

    _full = field_validator("full", mode="before")(parse_flag)


class SearchQuery(QueryModel):
    """Query for GET /api/search."""

    q: str = Field(default="", validate_default=True, description="Search text")
    limit: int = Field(default=20, description="Results per page (clamped to 1..SEARCH_MAX_LIMIT)")
    offset: int = Field(default=0, description="Results to skip")

    @field_validator("q")
    @classmethod
    def _query_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Search query is required")
        if len(value) > Config.SEARCH_MAX_QUERY_LENGTH:
            raise ValueError(
                f"Search query too long (max {Config.SEARCH_MAX_QUERY_LENGTH} characters)"
            )
        return value

    @field_validator("limit", mode="before")
    @classmethod
    def _page_size(cls, value: Any) -> Any:
        return parse_int(value, 20, 1, Config.SEARCH_MAX_LIMIT)

    @field_validator("offset", mode="before")
    @classmethod
    def _offset(cls, value: Any) -> Any:
        return parse_int(value, 0, 0)
