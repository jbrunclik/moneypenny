"""Helper functions shared across API routes.

This module exports validation helpers and chat streaming utilities
that are used by multiple route handlers.
"""

from src.api.helpers.chat_streaming import (
    SaveResult,
    cleanup_and_save,
    save_message_to_db,
    stream_events,
)
from src.api.helpers.validation import (
    get_conversation_or_404,
    get_message_or_404,
    validate_and_prepare_files,
)

__all__ = [
    # Validation helpers
    "get_conversation_or_404",
    "get_message_or_404",
    "validate_and_prepare_files",
    # Chat streaming helpers
    "SaveResult",
    "save_message_to_db",
    "stream_events",
    "cleanup_and_save",
]
