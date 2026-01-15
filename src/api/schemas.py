"""Pydantic schemas for API request and response validation.

This module defines Pydantic models for all API payloads. Request schemas
provide automatic validation of request structure, types, and constraints.
Response schemas provide OpenAPI documentation and response validation.

For file content validation (base64 decoding, size limits), see validate_files()
in src/utils/files.py which handles the content-level validation after Pydantic
validates the structure.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from src.config import Config

# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------


class MessageRole(str, Enum):
    """Role of a message sender."""

    USER = "user"
    ASSISTANT = "assistant"


class ThumbnailStatus(str, Enum):
    """Status of thumbnail generation."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class PaginationDirection(str, Enum):
    """Direction for cursor-based pagination.

    Used when fetching paginated results relative to a cursor position.
    """

    OLDER = "older"
    NEWER = "newer"


# -----------------------------------------------------------------------------
# File Schema (reusable)
# -----------------------------------------------------------------------------


class FileAttachment(BaseModel):
    """Schema for file attachments in chat requests.

    Validates structure only. Content validation (base64 decoding, size checking)
    is handled by validate_files() in src/utils/files.py.
    """

    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., min_length=1)  # MIME type
    data: str = Field(..., min_length=1)  # Base64-encoded data

    @field_validator("type")
    @classmethod
    def validate_mime_type(cls, v: str) -> str:
        """Validate MIME type is in allowed list."""
        if v not in Config.ALLOWED_FILE_TYPES:
            allowed = ", ".join(sorted(Config.ALLOWED_FILE_TYPES))
            raise ValueError(f"File type '{v}' not allowed. Allowed: {allowed}")
        return v


# -----------------------------------------------------------------------------
# Auth Schemas
# -----------------------------------------------------------------------------


class GoogleAuthRequest(BaseModel):
    """Schema for POST /auth/google."""

    credential: str = Field(..., min_length=1)


class TodoistConnectRequest(BaseModel):
    """Schema for POST /auth/todoist/connect - Exchange OAuth code for token."""

    code: str = Field(..., min_length=1, description="OAuth authorization code from Todoist")
    state: str = Field(..., min_length=1, description="CSRF state token for validation")


class GoogleCalendarConnectRequest(BaseModel):
    """Schema for POST /auth/calendar/connect - Exchange OAuth code for token."""

    code: str = Field(..., min_length=1, description="OAuth authorization code from Google")
    state: str = Field(..., min_length=1, description="CSRF state token for validation")


# -----------------------------------------------------------------------------
# Conversation Schemas
# -----------------------------------------------------------------------------


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


# -----------------------------------------------------------------------------
# Chat Schemas
# -----------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """Schema for POST /api/conversations/<conv_id>/chat/batch and /chat/stream.

    Validates structure. File content validation happens separately via
    validate_files() in src/utils/files.py.
    """

    message: str = Field(default="")
    files: list[FileAttachment] = Field(default_factory=list)
    force_tools: list[str] = Field(default_factory=list)
    anonymous_mode: bool = Field(default=False)

    @field_validator("files")
    @classmethod
    def validate_files_count(cls, v: list[FileAttachment]) -> list[FileAttachment]:
        """Validate file count limit."""
        if len(v) > Config.MAX_FILES_PER_MESSAGE:
            raise ValueError(f"Too many files. Maximum is {Config.MAX_FILES_PER_MESSAGE}")
        return v

    @model_validator(mode="after")
    def validate_message_or_files(self) -> ChatRequest:
        """Ensure at least message or files is provided."""
        message_text = self.message.strip() if self.message else ""
        if not message_text and not self.files:
            raise ValueError("Message or files required")
        return self


# -----------------------------------------------------------------------------
# Settings Schemas
# -----------------------------------------------------------------------------


class UpdateSettingsRequest(BaseModel):
    """Schema for PATCH /api/users/me/settings."""

    custom_instructions: str | None = Field(None, max_length=2000)


# =============================================================================
# Response Schemas
# =============================================================================

# -----------------------------------------------------------------------------
# Common Response Components
# -----------------------------------------------------------------------------


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


# -----------------------------------------------------------------------------
# User Schemas
# -----------------------------------------------------------------------------


class UserResponse(BaseModel):
    """User information."""

    id: str
    email: str
    name: str
    picture: str | None = None


class UserContainerResponse(BaseModel):
    """Response containing user info (used by /auth/me)."""

    user: UserResponse


# -----------------------------------------------------------------------------
# Auth Response Schemas
# -----------------------------------------------------------------------------


class AuthResponse(BaseModel):
    """Response from successful authentication."""

    token: str = Field(..., description="JWT token for subsequent requests")
    user: UserResponse


class TokenRefreshResponse(BaseModel):
    """Response from token refresh."""

    token: str = Field(..., description="New JWT token")


class TodoistAuthUrlResponse(BaseModel):
    """Response containing Todoist OAuth authorization URL."""

    auth_url: str = Field(..., description="URL to redirect user for Todoist authorization")
    state: str = Field(..., description="CSRF state token to validate on callback")


class TodoistConnectResponse(BaseModel):
    """Response from successful Todoist connection."""

    connected: bool = Field(..., description="Whether connection was successful")
    todoist_email: str | None = Field(None, description="Email of connected Todoist account")


class TodoistStatusResponse(BaseModel):
    """Response containing Todoist connection status."""

    connected: bool = Field(..., description="Whether Todoist is connected")
    todoist_email: str | None = Field(None, description="Email of connected Todoist account")
    connected_at: str | None = Field(None, description="ISO timestamp when connected")
    needs_reconnect: bool = Field(
        False, description="True if token is invalid and user needs to reconnect"
    )


class GoogleCalendarAuthUrlResponse(BaseModel):
    """Response containing Google Calendar OAuth authorization URL."""

    auth_url: str = Field(..., description="URL to redirect user for Google authorization")
    state: str = Field(..., description="CSRF state token to validate on callback")


class GoogleCalendarConnectResponse(BaseModel):
    """Response from successful Google Calendar connection."""

    connected: bool = Field(..., description="Whether connection was successful")
    calendar_email: str | None = Field(
        None, description="Email of Google account granting Calendar access"
    )


class GoogleCalendarStatusResponse(BaseModel):
    """Response containing Google Calendar connection status."""

    connected: bool = Field(..., description="Whether Google Calendar is connected")
    calendar_email: str | None = Field(None, description="Email of connected Google account")
    connected_at: str | None = Field(None, description="ISO timestamp when connected")
    needs_reconnect: bool = Field(
        False, description="True if tokens are invalid/expired and user must reconnect"
    )


class Calendar(BaseModel):
    """A Google Calendar."""

    id: str = Field(..., description="Calendar ID")
    summary: str = Field(..., description="Calendar name/title")
    primary: bool = Field(..., description="Whether this is the user's primary calendar")
    access_role: str = Field(..., description="User's access level (owner, writer, reader)")
    background_color: str | None = Field(None, description="Calendar background color (hex)")


class CalendarListResponse(BaseModel):
    """Response for listing available calendars."""

    calendars: list[Calendar] = Field(
        default_factory=list, description="List of available calendars"
    )
    error: str | None = Field(None, description="Error message if fetch failed")


class SelectedCalendarsResponse(BaseModel):
    """Response for selected calendars."""

    calendar_ids: list[str] = Field(..., description="List of selected calendar IDs")


class UpdateSelectedCalendarsRequest(BaseModel):
    """Request to update selected calendars."""

    calendar_ids: list[str] = Field(..., description="List of calendar IDs to fetch events from")


class ClientIdResponse(BaseModel):
    """Response containing Google Client ID."""

    client_id: str


# -----------------------------------------------------------------------------
# File Response Schemas
# -----------------------------------------------------------------------------


class FileMetadataResponse(BaseModel):
    """File metadata in message responses (excludes full data for performance)."""

    name: str
    type: str
    messageId: str | None = None
    fileIndex: int | None = None


class SourceResponse(BaseModel):
    """Web search source citation."""

    title: str
    url: str


class GeneratedImageResponse(BaseModel):
    """Generated image metadata."""

    prompt: str
    image_index: int | None = None


# -----------------------------------------------------------------------------
# Message Response Schemas
# -----------------------------------------------------------------------------


class MessageResponse(BaseModel):
    """Message in a conversation."""

    id: str
    role: Literal["user", "assistant"]
    content: str
    files: list[FileMetadataResponse] | None = None
    sources: list[SourceResponse] | None = None
    generated_images: list[GeneratedImageResponse] | None = None
    language: str | None = Field(
        default=None, description="ISO 639-1 language code for TTS (e.g., 'en', 'cs')"
    )
    created_at: str


class ChatBatchResponse(BaseModel):
    """Response from batch chat endpoint."""

    id: str
    role: Literal["assistant"] = "assistant"
    content: str
    files: list[FileMetadataResponse] | None = None
    sources: list[SourceResponse] | None = None
    generated_images: list[GeneratedImageResponse] | None = None
    language: str | None = Field(
        default=None, description="ISO 639-1 language code for TTS (e.g., 'en', 'cs')"
    )
    created_at: str
    title: str | None = Field(
        default=None, description="Auto-generated conversation title (first message only)"
    )
    user_message_id: str | None = Field(
        default=None, description="Real ID of the user message (for updating temp IDs in frontend)"
    )


# -----------------------------------------------------------------------------
# Conversation Response Schemas
# -----------------------------------------------------------------------------


class ConversationResponse(BaseModel):
    """Conversation summary (without messages)."""

    id: str
    title: str
    model: str
    created_at: str
    updated_at: str
    message_count: int | None = None


class ConversationDetailResponse(BaseModel):
    """Full conversation with messages."""

    id: str
    title: str
    model: str
    created_at: str
    updated_at: str
    messages: list[MessageResponse]


class ConversationsListResponse(BaseModel):
    """List of conversations."""

    conversations: list[ConversationResponse]


class SyncConversationResponse(BaseModel):
    """Conversation summary for sync endpoint."""

    id: str
    title: str
    model: str
    updated_at: str
    message_count: int


class SyncResponse(BaseModel):
    """Response from sync endpoint."""

    conversations: list[SyncConversationResponse]
    server_time: str = Field(..., description="ISO timestamp to use for next sync")
    is_full_sync: bool


# -----------------------------------------------------------------------------
# Model Response Schemas
# -----------------------------------------------------------------------------


class ModelResponse(BaseModel):
    """Available model info."""

    id: str
    name: str
    short_name: str = Field(
        ..., description="Short display name for compact UI (e.g., 'Fast', 'Advanced')"
    )


class ModelsListResponse(BaseModel):
    """List of available models."""

    models: list[ModelResponse]
    default: str = Field(..., description="Default model ID")


# -----------------------------------------------------------------------------
# Config Response Schemas
# -----------------------------------------------------------------------------


class UploadConfigResponse(BaseModel):
    """File upload configuration."""

    maxFileSize: int = Field(..., description="Maximum file size in bytes")
    maxFilesPerMessage: int = Field(..., description="Maximum files per message")
    allowedFileTypes: list[str] = Field(..., description="Allowed MIME types")


# -----------------------------------------------------------------------------
# Version and Health Response Schemas
# -----------------------------------------------------------------------------


class VersionResponse(BaseModel):
    """App version info."""

    version: str | None = Field(default=None, description="App version (JS bundle hash)")


class HealthResponse(BaseModel):
    """Liveness probe response."""

    status: str
    version: str | None = None


class HealthCheckDetail(BaseModel):
    """Individual health check result."""

    status: str
    message: str | None = None


class ReadinessResponse(BaseModel):
    """Readiness probe response."""

    status: str = Field(..., description="'ready' or 'not_ready'")
    checks: dict[str, HealthCheckDetail]
    version: str | None = None


# -----------------------------------------------------------------------------
# Cost Response Schemas
# -----------------------------------------------------------------------------


class ConversationCostResponse(BaseModel):
    """Cost for a conversation."""

    conversation_id: str
    cost_usd: float
    cost: float = Field(..., description="Cost in display currency")
    currency: str
    formatted: str


class MessageCostResponse(BaseModel):
    """Cost breakdown for a message."""

    message_id: str
    cost_usd: float
    cost: float = Field(..., description="Cost in display currency")
    currency: str
    formatted: str
    input_tokens: int
    output_tokens: int
    model: str
    image_generation_cost_usd: float | None = None
    image_generation_cost: float | None = None
    image_generation_cost_formatted: str | None = None


class ModelCostBreakdown(BaseModel):
    """Cost breakdown by model."""

    total: float
    total_usd: float
    message_count: int
    formatted: str


class MonthlyCostResponse(BaseModel):
    """Monthly cost for a user."""

    user_id: str
    year: int
    month: int
    total_usd: float
    total: float = Field(..., description="Total in display currency")
    currency: str
    formatted: str
    message_count: int
    breakdown: dict[str, ModelCostBreakdown]


class MonthCostEntry(BaseModel):
    """Single month in cost history."""

    year: int
    month: int
    total_usd: float
    total: float
    currency: str
    formatted: str
    message_count: int


class CostHistoryResponse(BaseModel):
    """Cost history for a user."""

    user_id: str
    history: list[MonthCostEntry]


# -----------------------------------------------------------------------------
# Settings Response Schemas
# -----------------------------------------------------------------------------


class UserSettingsResponse(BaseModel):
    """User settings."""

    custom_instructions: str = Field(default="", description="Custom instructions for the AI")


# -----------------------------------------------------------------------------
# Memory Response Schemas
# -----------------------------------------------------------------------------


class MemoryResponse(BaseModel):
    """Single memory entry."""

    id: str
    content: str
    category: str | None = None
    created_at: str
    updated_at: str


class MemoriesListResponse(BaseModel):
    """List of memories."""

    memories: list[MemoryResponse]


# -----------------------------------------------------------------------------
# Thumbnail Response Schema
# -----------------------------------------------------------------------------


class ThumbnailPendingResponse(BaseModel):
    """Response when thumbnail is still being generated (202)."""

    status: Literal["pending"] = "pending"


# -----------------------------------------------------------------------------
# Pagination Response Schemas
# -----------------------------------------------------------------------------


class ConversationsPaginationResponse(BaseModel):
    """Pagination info for conversations list."""

    next_cursor: str | None = Field(
        default=None, description="Cursor for fetching next page (null if no more)"
    )
    has_more: bool = Field(..., description="Whether there are more pages")
    total_count: int = Field(..., description="Total number of conversations")


class ConversationsListPaginatedResponse(BaseModel):
    """Paginated list of conversations."""

    conversations: list[ConversationResponse]
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
    messages: list[MessageResponse]
    message_pagination: MessagesPaginationResponse


class MessagesListResponse(BaseModel):
    """Paginated messages response (for dedicated messages endpoint)."""

    messages: list[MessageResponse]
    pagination: MessagesPaginationResponse


# -----------------------------------------------------------------------------
# Search Schemas
# -----------------------------------------------------------------------------


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


# -----------------------------------------------------------------------------
# Planner Response Schemas
# -----------------------------------------------------------------------------


class PlannerTaskResponse(BaseModel):
    """A task from Todoist for the planner dashboard."""

    id: str
    content: str
    description: str = ""
    due_date: str | None = Field(default=None, description="Due date in YYYY-MM-DD format")
    due_string: str | None = Field(
        default=None, description="Human-readable due string (e.g., 'tomorrow at 3pm')"
    )
    priority: int = Field(default=1, ge=1, le=4, description="Priority 1-4 (4 is highest)")
    project_name: str | None = None
    section_name: str | None = None
    labels: list[str] = Field(default_factory=list)
    is_recurring: bool = False
    url: str | None = Field(default=None, description="Direct URL to task in Todoist")


class PlannerEventAttendeeResponse(BaseModel):
    """An attendee on a calendar event."""

    email: str | None = None
    response_status: str | None = Field(
        default=None, description="RSVP status: accepted/tentative/declined/needsAction"
    )
    self: bool = Field(default=False, description="True if this is the current user")


class PlannerEventOrganizerResponse(BaseModel):
    """The organizer/creator of a calendar event."""

    email: str | None = None
    display_name: str | None = Field(default=None, description="Display name of organizer")
    self: bool = Field(default=False, description="True if this is the current user")


class PlannerEventResponse(BaseModel):
    """A calendar event for the planner dashboard."""

    id: str
    summary: str
    description: str | None = None
    start: str | None = Field(default=None, description="Start datetime (ISO format)")
    end: str | None = Field(default=None, description="End datetime (ISO format)")
    start_date: str | None = Field(
        default=None, description="Start date for all-day events (YYYY-MM-DD)"
    )
    end_date: str | None = Field(
        default=None, description="End date for all-day events (YYYY-MM-DD)"
    )
    location: str | None = None
    html_link: str | None = Field(
        default=None, description="Direct URL to event in Google Calendar"
    )
    is_all_day: bool = False
    attendees: list[PlannerEventAttendeeResponse] = Field(default_factory=list)
    organizer: PlannerEventOrganizerResponse | None = Field(
        default=None, description="Event organizer/creator"
    )
    calendar_id: str | None = Field(
        default=None, description="Source calendar ID (e.g., 'primary', email address)"
    )
    calendar_summary: str | None = Field(default=None, description="Source calendar name/title")


class PlannerDayResponse(BaseModel):
    """A single day in the planner dashboard."""

    date: str = Field(..., description="Date in YYYY-MM-DD format")
    day_name: str = Field(..., description="Day label (Today, Tomorrow, or weekday name)")
    events: list[PlannerEventResponse] = Field(default_factory=list)
    tasks: list[PlannerTaskResponse] = Field(default_factory=list)


class PlannerDashboardResponse(BaseModel):
    """Complete planner dashboard data."""

    days: list[PlannerDayResponse] = Field(
        ..., description="7 days of events and tasks starting from today"
    )
    overdue_tasks: list[PlannerTaskResponse] = Field(
        default_factory=list, description="Tasks that are past their due date"
    )
    todoist_connected: bool = Field(default=False, description="Whether Todoist is connected")
    calendar_connected: bool = Field(
        default=False, description="Whether Google Calendar is connected"
    )
    todoist_error: str | None = Field(
        default=None, description="Error message if Todoist fetch failed"
    )
    calendar_error: str | None = Field(
        default=None, description="Error message if Calendar fetch failed"
    )
    server_time: str = Field(..., description="Server timestamp for cache validation")


class PlannerConversationResponse(BaseModel):
    """Planner conversation with messages."""

    id: str
    title: str
    model: str
    created_at: str
    updated_at: str
    messages: list[MessageResponse]
    was_reset: bool = Field(
        default=False, description="True if the conversation was auto-reset due to 4am cutoff"
    )


class PlannerResetResponse(BaseModel):
    """Response from planner reset endpoint."""

    success: bool = True
    message: str = "Planner conversation reset"


class PlannerConversationSyncData(BaseModel):
    """Planner conversation data for sync."""

    id: str
    updated_at: str
    message_count: int
    last_reset: str | None = Field(default=None, description="Timestamp of last reset")


class PlannerSyncResponse(BaseModel):
    """Response from planner sync endpoint for real-time synchronization."""

    conversation: PlannerConversationSyncData | None = Field(
        default=None, description="Planner conversation state, or null if no planner exists"
    )
    server_time: str = Field(..., description="Server timestamp in ISO format")


# ============ Canvas Schemas ============


class UpdateCanvasRequest(BaseModel):
    """Request to update canvas file content."""

    content: str = Field(..., description="New canvas content (UTF-8 text)")


class CanvasMetadata(BaseModel):
    """Canvas document metadata for LLM responses."""

    title: str = Field(..., description="Canvas document title")
    index: int = Field(default=0, description="Index in canvas_documents array")


class CanvasDocument(BaseModel):
    """Canvas document in list response."""

    message_id: str = Field(..., description="Message ID containing this canvas")
    file_index: int = Field(..., description="File index in message.files array")
    title: str = Field(..., description="Canvas document title")
    conversation_id: str = Field(..., description="Conversation ID")
    conversation_title: str = Field(..., description="Conversation title")
    created_at: str = Field(..., description="Creation timestamp (ISO format)")
    updated_at: str = Field(..., description="Last update timestamp (ISO format)")


class CanvasListResponse(BaseModel):
    """Response containing list of user's canvas documents."""

    canvases: list[CanvasDocument] = Field(..., description="List of canvas documents")
    total: int = Field(..., description="Total number of canvas documents")
