"""Validation helper functions for API routes.

This module provides common validation patterns used across multiple route handlers.
"""

from typing import Any

from src.api.errors import raise_not_found_error, raise_validation_error
from src.db.models import Conversation, Message, User, db
from src.utils.background_thumbnails import mark_files_for_thumbnail_generation
from src.utils.files import validate_files
from src.utils.logging import get_logger

logger = get_logger(__name__)


def get_conversation_or_404(conv_id: str, user_id: str, context: str = "operation") -> Conversation:
    """Get conversation or raise 404 error.

    Args:
        conv_id: Conversation ID
        user_id: User ID (for ownership verification)
        context: Context string for logging (e.g., "chat", "cost query")

    Returns:
        Conversation object if found

    Raises:
        NotFoundError: If conversation not found or doesn't belong to user
    """
    conv = db.get_conversation(conv_id, user_id)
    if not conv:
        logger.warning(
            f"Conversation not found for {context}",
            extra={"user_id": user_id, "conversation_id": conv_id},
        )
        raise_not_found_error("Conversation")
    return conv


def get_message_or_404(message_id: str, user_id: str, context: str = "operation") -> Message:
    """Get message or raise 404 error.

    Args:
        message_id: Message ID
        user_id: User ID (for ownership verification via conversation)
        context: Context string for logging (e.g., "cost query", "file access")

    Returns:
        Message object if found and user owns the conversation

    Raises:
        NotFoundError: If message not found or user doesn't own the conversation
    """
    message = db.get_message_by_id(message_id)
    if not message:
        logger.warning(
            f"Message not found for {context}",
            extra={"user_id": user_id, "message_id": message_id},
        )
        raise_not_found_error("Message")

    # Verify user owns the conversation
    conv = db.get_conversation(message.conversation_id, user_id)
    if not conv:
        logger.warning(
            f"Unauthorized access to message for {context}",
            extra={"user_id": user_id, "message_id": message_id},
        )
        raise_not_found_error("Message")

    return message


def validate_and_prepare_files(
    files: list[dict[str, Any]],
    user: User,
    conversation_id: str,
) -> list[dict[str, Any]]:
    """Validate files and mark for thumbnail generation.

    Args:
        files: List of file dictionaries
        user: User object (for logging)
        conversation_id: Conversation ID (for logging)

    Returns:
        Files marked for thumbnail generation

    Raises:
        ValidationError: If file validation fails
    """
    if not files:
        return []

    logger.debug(
        "Validating files",
        extra={"user_id": user.id, "conversation_id": conversation_id, "file_count": len(files)},
    )

    is_valid, error = validate_files(files)
    if not is_valid:
        logger.warning(
            "File validation failed",
            extra={
                "user_id": user.id,
                "conversation_id": conversation_id,
                "error": error,
            },
        )
        raise_validation_error(error)

    # Mark files for thumbnail generation
    files = mark_files_for_thumbnail_generation(files)
    return files
