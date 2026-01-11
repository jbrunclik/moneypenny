"""Context variables for tool execution.

This module provides context variables that allow tools to access
information about the current request, such as uploaded files and
conversation context.
"""

import contextvars
from typing import Any

# Contextvar to hold the current message's files for tool access
# This allows tools (like generate_image) to access uploaded images for image-to-image workflows
_current_message_files: contextvars.ContextVar[list[dict[str, Any]] | None] = (
    contextvars.ContextVar("_current_message_files", default=None)
)

# Contextvars to hold conversation context for tools that need to access history
# This allows tools (like retrieve_file) to access files from previous messages
_current_conversation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_conversation_id", default=None
)
_current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_user_id", default=None
)


def set_current_message_files(files: list[dict[str, Any]] | None) -> None:
    """Set the current message's files for tool access."""
    _current_message_files.set(files)


def get_current_message_files() -> list[dict[str, Any]] | None:
    """Get the current message's files (for tools like generate_image to access)."""
    return _current_message_files.get()


def set_conversation_context(conversation_id: str | None, user_id: str | None) -> None:
    """Set the conversation context for tool access.

    This allows tools to access files from conversation history.
    """
    _current_conversation_id.set(conversation_id)
    _current_user_id.set(user_id)


def get_conversation_context() -> tuple[str | None, str | None]:
    """Get the current conversation context (conversation_id, user_id)."""
    return _current_conversation_id.get(), _current_user_id.get()
