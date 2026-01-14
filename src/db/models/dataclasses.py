"""Database model dataclasses.

These dataclasses represent the core entities stored in the database.
They are returned by Database methods and used throughout the application.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.api.schemas import MessageRole


@dataclass
class User:
    """A user account with authentication and integration settings."""

    id: str
    email: str
    name: str
    picture: str | None
    created_at: datetime
    custom_instructions: str | None = None
    todoist_access_token: str | None = None
    todoist_connected_at: datetime | None = None
    google_calendar_access_token: str | None = None
    google_calendar_refresh_token: str | None = None
    google_calendar_token_expires_at: datetime | None = None
    google_calendar_connected_at: datetime | None = None
    google_calendar_email: str | None = None
    google_calendar_selected_ids: list[str] | None = None
    planner_last_reset_at: datetime | None = None


@dataclass
class Conversation:
    """A chat conversation belonging to a user."""

    id: str
    user_id: str
    title: str
    model: str
    created_at: datetime
    updated_at: datetime
    is_planning: bool = False
    last_reset: datetime | None = None  # For planner conversations


@dataclass
class Message:
    """A single message in a conversation."""

    id: str
    conversation_id: str
    role: MessageRole
    content: str  # Plain text message
    created_at: datetime
    files: list[dict[str, Any]] = field(default_factory=list)  # File attachments
    sources: list[dict[str, str]] | None = None  # Web sources for assistant messages
    generated_images: list[dict[str, str]] | None = None  # Generated image metadata
    has_cost: bool = False  # Whether cost tracking data exists for this message
    language: str | None = None  # ISO 639-1 language code (e.g., "en", "cs") for TTS


@dataclass
class Memory:
    """A user memory entry for context retention."""

    id: str
    user_id: str
    content: str
    category: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class MessagePagination:
    """Pagination info for messages.

    Contains cursors for navigating in both directions (older and newer messages).
    """

    older_cursor: str | None  # Cursor to fetch older messages
    newer_cursor: str | None  # Cursor to fetch newer messages
    has_older: bool  # True if there are older messages
    has_newer: bool  # True if there are newer messages
    total_count: int  # Total message count in conversation


@dataclass
class SearchResult:
    """A single search result from full-text search.

    Can be either a conversation title match or a message content match.
    """

    conversation_id: str
    conversation_title: str
    message_id: str | None  # None if match is on conversation title
    message_content: str | None  # Snippet with highlight markers
    match_type: str  # "conversation" or "message"
    rank: float  # BM25 relevance score (lower is better)
    created_at: datetime | None  # Message timestamp (None for title matches)
