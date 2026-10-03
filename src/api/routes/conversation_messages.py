"""Message routes: single message fetch/delete, message pages, truncation.

Attached to conversations.api (one shared "Conversations" blueprint keeps a
single OpenAPI tag and the original endpoint names).
"""

from typing import Any

from flask import request

from src.api.errors import raise_conflict_error, raise_not_found_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.routes.conversations import api
from src.api.schemas.chat import MessageResponse, ResearchOfferUpdate
from src.api.schemas.common import PaginationDirection, StatusResponse
from src.api.schemas.conversations import (
    MessagesListResponse,
    TruncateConversationRequest,
    TruncateConversationResponse,
)
from src.api.utils import normalize_generated_images, serialize_messages_for_response
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import Message, MessagePagination, User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)


@api.route("/messages/<message_id>", methods=["GET"])
@api.output(MessageResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
def get_message(user: User, message_id: str) -> tuple[dict[str, Any], int]:
    """Get a single message by ID.

    Fetches a specific message. The message must belong to a conversation
    owned by the authenticated user. Useful for stream recovery when the
    connection drops but the message was saved server-side.
    """
    logger.debug("Getting message", extra={"user_id": user.id, "message_id": message_id})
    message = db.get_message_by_id(message_id)
    if not message:
        logger.warning(
            "Message not found",
            extra={"user_id": user.id, "message_id": message_id},
        )
        raise_not_found_error("Message")

    # Verify the message belongs to a conversation owned by this user
    conv = db.get_conversation(message.conversation_id, user.id)
    if not conv:
        logger.warning(
            "Message belongs to inaccessible conversation",
            extra={"user_id": user.id, "message_id": message_id},
        )
        raise_not_found_error("Message")

    # Convert to response format
    response = {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "files": message.files,
        "sources": message.sources,
        "generated_images": normalize_generated_images(message.generated_images),
        "language": message.language,
    }

    logger.debug("Message retrieved", extra={"user_id": user.id, "message_id": message_id})
    return response, 200


@api.route("/messages/<message_id>/research-offer", methods=["PATCH"])
@api.output(StatusResponse)
@api.doc(responses=[400, 404, 409, 429])
@rate_limit_conversations
@require_auth
@validate_request(ResearchOfferUpdate)
def update_research_offer(
    user: User, data: ResearchOfferUpdate, message_id: str
) -> tuple[dict[str, str], int]:
    """Decline a deep-research offer (starting one goes through the chat stream)."""
    from src.agent.deep_research.plan import OfferConflict, OfferNotFound, decline_offer

    message = db.get_message_by_id(message_id)
    if not message or not db.get_conversation(message.conversation_id, user.id):
        raise_not_found_error("Message")
    try:
        decline_offer(message)
    except OfferNotFound:
        raise_not_found_error("Research offer")
    except OfferConflict as e:
        raise_conflict_error(str(e))
    return {"status": data.status}, 200


@api.route("/conversations/<conv_id>/truncate", methods=["POST"])
@api.output(TruncateConversationResponse)
@api.doc(responses=[400, 404, 429])
@rate_limit_conversations
@require_auth
@validate_request(TruncateConversationRequest)
def truncate_conversation(
    user: User, data: TruncateConversationRequest, conv_id: str
) -> tuple[dict[str, int], int]:
    """Delete a conversation's tail from a given message.

    The shared primitive behind edit-and-resend (inclusive=true: the target
    message and everything after it) and regenerate (inclusive=false via the
    single-message DELETE instead). Blobs of deleted messages are removed;
    cost data is intentionally preserved.
    """
    conv = db.get_conversation(conv_id, user.id)
    if not conv:
        raise_not_found_error("Conversation")

    target = db.get_message_by_id(data.message_id)
    if not target or target.conversation_id != conv_id:
        raise_not_found_error("Message")

    deleted = db.delete_messages_after(conv_id, user.id, data.message_id, data.inclusive)
    logger.info(
        "Conversation truncated",
        extra={
            "user_id": user.id,
            "conversation_id": conv_id,
            "message_id": data.message_id,
            "inclusive": data.inclusive,
            "deleted": deleted,
        },
    )
    return {"deleted": deleted}, 200


@api.route("/messages/<message_id>", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
def delete_message(user: User, message_id: str) -> tuple[dict[str, str], int]:
    """Delete a message.

    Deletes a single message and its associated files/thumbnails.
    The message must belong to a conversation owned by the authenticated user.
    Cost data is intentionally preserved for accurate reporting.
    """
    logger.debug("Deleting message", extra={"user_id": user.id, "message_id": message_id})
    if not db.delete_message(message_id, user.id):
        logger.warning(
            "Message not found for deletion",
            extra={"user_id": user.id, "message_id": message_id},
        )
        raise_not_found_error("Message")

    logger.info("Message deleted", extra={"user_id": user.id, "message_id": message_id})
    return {"status": "deleted"}, 200


def _messages_around(
    user: User, conv_id: str, around_message_id: str, limit: int
) -> tuple[list[Message], MessagePagination]:
    """Load messages around the target message (for search result navigation)."""
    # Split the limit between before and after the target
    before_limit = limit // 2
    after_limit = limit - before_limit
    result = db.get_messages_around(
        conv_id, around_message_id, before_limit=before_limit, after_limit=after_limit
    )
    if result is None:
        logger.warning(
            "Message not found for around query",
            extra={
                "user_id": user.id,
                "conversation_id": conv_id,
                "around_message_id": around_message_id,
            },
        )
        raise_not_found_error("Message")
    return result


@api.route("/conversations/<conv_id>/messages", methods=["GET"])
@api.output(MessagesListResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
def get_messages(user: User, conv_id: str) -> tuple[dict[str, Any], int]:
    """Get paginated messages for a conversation.

    This is a dedicated endpoint for fetching message pages, more efficient
    than the full conversation endpoint when only messages are needed.

    Query parameters:
    - limit: Number of messages to return (default: 50, max: 200)
    - cursor: Cursor for fetching older/newer messages
    - direction: "older" (default) or "newer" for pagination direction
    - around_message_id: Load messages around a specific message (for search navigation)
      When specified, cursor and direction are ignored.

    By default, returns the newest messages.
    """
    # Parse pagination parameters
    limit_param = request.args.get("limit")
    cursor_param = request.args.get("cursor")
    direction_param = request.args.get("direction", PaginationDirection.OLDER.value)
    around_message_id = request.args.get("around_message_id")

    # Validate and clamp limit
    if limit_param:
        try:
            limit = int(limit_param)
            limit = max(1, min(limit, Config.MESSAGES_MAX_PAGE_SIZE))
        except ValueError:
            limit = Config.MESSAGES_DEFAULT_PAGE_SIZE
    else:
        limit = Config.MESSAGES_DEFAULT_PAGE_SIZE

    # Validate direction
    try:
        direction = PaginationDirection(direction_param)
    except ValueError:
        direction = PaginationDirection.OLDER

    logger.debug(
        "Getting messages",
        extra={
            "user_id": user.id,
            "conversation_id": conv_id,
            "limit": limit,
            "cursor": cursor_param,
            "direction": direction.value,
            "around_message_id": around_message_id,
        },
    )

    # Verify conversation exists and belongs to user
    conv = db.get_conversation(conv_id, user.id)
    if not conv:
        logger.warning(
            "Conversation not found",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        raise_not_found_error("Conversation")

    # Get messages - either around a specific message or with standard pagination
    if around_message_id:
        messages, pagination = _messages_around(user, conv_id, around_message_id, limit)
    else:
        # Standard cursor-based pagination
        messages, pagination = db.get_messages_paginated(
            conv_id, limit=limit, cursor=cursor_param, direction=direction
        )

    logger.info(
        "Messages retrieved",
        extra={
            "user_id": user.id,
            "conversation_id": conv_id,
            "message_count": len(messages),
            "total_messages": pagination.total_count,
            "has_older": pagination.has_older,
            "has_newer": pagination.has_newer,
        },
    )

    # Optimize file data
    optimized_messages = serialize_messages_for_response(messages)

    return {
        "messages": optimized_messages,
        "pagination": {
            "older_cursor": pagination.older_cursor,
            "newer_cursor": pagination.newer_cursor,
            "has_older": pagination.has_older,
            "has_newer": pagination.has_newer,
            "total_count": pagination.total_count,
        },
    }, 200
