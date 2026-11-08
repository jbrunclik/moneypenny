"""Context variables for tool execution.

This module provides context variables that allow tools to access
information about the current request, such as uploaded files and
conversation context.
"""

import contextvars
from typing import Any

from src.utils.files import UploadedFile

# Contextvar to hold the current message's files for tool access
# This allows tools (like generate_image) to access uploaded images for image-to-image workflows
_current_message_files: contextvars.ContextVar[list[UploadedFile] | None] = contextvars.ContextVar(
    "_current_message_files", default=None
)

# Contextvars to hold conversation context for tools that need to access history
# This allows tools (like retrieve_file) to access files from previous messages
_current_conversation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_conversation_id", default=None
)
_current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_user_id", default=None
)

# Contextvar to hold the current agent name (for autonomous agent executions)
_current_agent_name: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_agent_name", default=None
)

# Contextvar holding the device location for the current request (never persisted)
_client_location: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "_client_location", default=None
)


def set_location_context(location: dict[str, Any] | None) -> None:
    """Set the device location for tool/prompt access (ClientLocation.model_dump())."""
    _client_location.set(location)


def get_location_context() -> dict[str, Any] | None:
    """Get the device location for the current request, if shared."""
    return _client_location.get()


def set_current_message_files(files: list[UploadedFile] | None) -> None:
    """Set the current message's files for tool access."""
    _current_message_files.set(files)


def get_current_message_files() -> list[UploadedFile] | None:
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


def set_agent_name(agent_name: str | None) -> None:
    """Set the current agent name for tool access.

    This is used by autonomous agents to identify themselves in tools like WhatsApp.
    """
    _current_agent_name.set(agent_name)


def get_agent_name() -> str | None:
    """Get the current agent name (for autonomous agent executions)."""
    return _current_agent_name.get()


# The kv_store namespace of the standing chat this turn is in (agent:<id>,
# sports, language); None in ordinary chats, where kv_store is not bound
_standing_namespace: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_standing_namespace", default=None
)


def set_standing_namespace(namespace: str | None) -> None:
    """Set the standing chat's kv namespace for this turn (None clears it)."""
    _standing_namespace.set(namespace)


def get_standing_namespace() -> str | None:
    """The standing chat's kv namespace for this turn, if any."""
    return _standing_namespace.get()
