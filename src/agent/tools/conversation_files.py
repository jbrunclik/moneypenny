"""Files uploaded in the current conversation, resolved by their history id.

The history metadata lists each user message's files as ``message_id:file_index``.
retrieve_file and execute_code(files=...) both load them here, with the same
checks: a conversation context, the user owns the conversation, the message
belongs to it, the index exists, and the attachment is within retention.
"""

import base64
from dataclasses import dataclass

from src.agent.tools.context import get_conversation_context
from src.agent.tools.errors import tool_error
from src.db.blob_store import get_blob_store
from src.db.models import db, make_blob_key
from src.services.file_retention import is_file_expired, retention_note
from src.utils.files import StoredFile
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ConversationFile:
    """A conversation attachment's bytes, as stored."""

    file_id: str
    name: str
    mime_type: str
    data: bytes


def parse_file_id(file_id: str) -> tuple[str, int] | None:
    """``message_id:file_index`` -> (message_id, index); None when malformed."""
    message_id, sep, index = file_id.rpartition(":")
    # ASCII only: '²'.isdigit() is True, but int('²') raises
    if not sep or not message_id or not (index.isascii() and index.isdigit()):
        return None
    return message_id, int(index)


def load_conversation_file(message_id: str, file_index: int) -> ConversationFile | str:
    """The attachment, or a tool error (JSON) saying why it cannot be read."""
    conv_id, user_id = get_conversation_context()

    if not conv_id or not user_id:
        logger.warning("retrieve_file called without conversation context")
        return tool_error(
            "No conversation context available. This tool can only be used during a chat."
        )

    # Verify user owns the conversation
    conv = db.get_conversation(conv_id, user_id)
    if not conv:
        logger.warning(
            "conversation file: conversation not found or not authorized",
            extra={"conv_id": conv_id, "user_id": user_id},
        )
        return tool_error("Conversation not found or not authorized.")

    logger.info(
        "conversation file: retrieving file",
        extra={
            "conv_id": conv_id,
            "message_id": message_id,
            "file_index": file_index,
        },
    )

    # Get the message
    message = db.get_message_by_id(message_id)
    if not message:
        logger.warning(
            "conversation file: message not found",
            extra={"message_id": message_id},
        )
        return tool_error(f"Message not found: {message_id}")

    # Verify message belongs to this conversation
    if message.conversation_id != conv_id:
        logger.warning(
            "conversation file: message belongs to different conversation",
            extra={
                "message_id": message_id,
                "message_conv_id": message.conversation_id,
                "current_conv_id": conv_id,
            },
        )
        return tool_error("Message does not belong to this conversation.")

    # Check file exists
    if not message.files or not 0 <= file_index < len(message.files):
        logger.warning(
            "conversation file: file not found",
            extra={
                "message_id": message_id,
                "file_index": file_index,
                "file_count": len(message.files) if message.files else 0,
            },
        )
        return tool_error(
            f"File index {file_index} not found in message. Message has {len(message.files) if message.files else 0} file(s)."
        )

    file_meta = message.files[file_index]
    file_name = file_meta.get("name", f"file_{file_index}")
    mime_type = file_meta.get("type", "application/octet-stream")

    # Age-based retention gate: stays truthful even before the physical
    # sweep has deleted the blob (videos 7 days, images 30 days)
    if is_file_expired(mime_type, message.created_at):
        return tool_error(
            f"This file has been cleaned up and is no longer available. "
            f"{retention_note(mime_type)}."
        )

    loaded = _load_file_data(message_id, file_index, file_meta, mime_type)
    if isinstance(loaded, str):
        return loaded
    binary_data, mime_type = loaded

    logger.info(
        "conversation file: file retrieved successfully",
        extra={
            "message_id": message_id,
            "file_index": file_index,
            "file_name": file_name,
            "mime_type": mime_type,
            "size": len(binary_data),
        },
    )
    return ConversationFile(f"{message_id}:{file_index}", file_name, mime_type, binary_data)


def _load_file_data(
    message_id: str, file_index: int, file_meta: StoredFile, mime_type: str
) -> tuple[bytes, str] | str:
    """The file's bytes and MIME type, or a tool error when they cannot be read."""
    # Get file data from blob store
    blob_store = get_blob_store()
    blob_key = make_blob_key(message_id, file_index)
    blob_result = blob_store.get(blob_key)

    if blob_result:
        binary_data, stored_mime_type = blob_result
        # Use stored MIME type if available
        return binary_data, stored_mime_type or mime_type

    # Fall back to legacy base64 data in message
    if "data" not in file_meta:
        logger.warning(
            "retrieve_file: no file data found",
            extra={"message_id": message_id, "file_index": file_index},
        )
        return tool_error("File data not found in storage.")
    try:
        return base64.b64decode(file_meta["data"]), mime_type
    except ValueError, TypeError:
        logger.error(  # noqa: TRY400 - corrupt stored data; a traceback adds nothing
            "retrieve_file: failed to decode legacy base64 data",
            extra={"message_id": message_id, "file_index": file_index},
        )
        return tool_error("Failed to read file data.")
