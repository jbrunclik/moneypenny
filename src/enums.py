"""Shared enums used across layers (api, agent, db, utils).

They live at the bottom of the layer order (B1) so every layer can import
them; API schemas reuse them for their fields.
"""

from enum import StrEnum


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
