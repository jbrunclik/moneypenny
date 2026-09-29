"""Conversation organization routes: archive, unarchive, pin, archived list.

Attached to conversations.api (one shared "Conversations" blueprint keeps a
single OpenAPI tag and the original endpoint names).
"""

from typing import Any

from flask import request

from src.api.errors import raise_not_found_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.routes.conversations import api
from src.api.schemas.common import StatusResponse
from src.api.schemas.conversations import ConversationsListPaginatedResponse
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)


@api.route("/conversations/archived", methods=["GET"])
@api.output(ConversationsListPaginatedResponse)
@api.doc(responses=[429])
@rate_limit_conversations
@require_auth
def list_archived_conversations(user: User) -> dict[str, Any]:
    """List archived conversations with pagination."""
    limit_param = request.args.get("limit")
    cursor_param = request.args.get("cursor")

    if limit_param:
        try:
            limit = int(limit_param)
            limit = max(1, min(limit, Config.CONVERSATIONS_MAX_PAGE_SIZE))
        except ValueError:
            limit = Config.CONVERSATIONS_DEFAULT_PAGE_SIZE
    else:
        limit = Config.CONVERSATIONS_DEFAULT_PAGE_SIZE

    conv_with_counts, next_cursor, has_more, total_count = db.list_archived_conversations_paginated(
        user.id, limit=limit, cursor=cursor_param
    )

    return {
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "model": c.model,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
                "message_count": message_count,
                "archived": True,
                "last_message_preview": preview,
            }
            for c, message_count, preview in conv_with_counts
        ],
        "pagination": {
            "next_cursor": next_cursor,
            "has_more": has_more,
            "total_count": total_count,
        },
    }


@api.route("/conversations/<conv_id>/archive", methods=["POST"])
@api.output(StatusResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
def archive_conversation(user: User, conv_id: str) -> tuple[dict[str, str], int]:
    """Archive a conversation (hide from main list)."""
    logger.debug("Archiving conversation", extra={"user_id": user.id, "conversation_id": conv_id})
    if not db.archive_conversation(conv_id, user.id):
        raise_not_found_error("Conversation")

    logger.info("Conversation archived", extra={"user_id": user.id, "conversation_id": conv_id})
    return {"status": "archived"}, 200


@api.route("/conversations/<conv_id>/pin", methods=["POST"])
@api.output(StatusResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
def pin_conversation(user: User, conv_id: str) -> tuple[dict[str, str], int]:
    """Pin a conversation to the top of the sidebar."""
    if not db.set_conversation_pinned(conv_id, user.id, True):
        raise_not_found_error("Conversation")
    logger.info("Conversation pinned", extra={"user_id": user.id, "conversation_id": conv_id})
    return {"status": "pinned"}, 200


@api.route("/conversations/<conv_id>/unpin", methods=["POST"])
@api.output(StatusResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
def unpin_conversation(user: User, conv_id: str) -> tuple[dict[str, str], int]:
    """Unpin a conversation."""
    if not db.set_conversation_pinned(conv_id, user.id, False):
        raise_not_found_error("Conversation")
    logger.info("Conversation unpinned", extra={"user_id": user.id, "conversation_id": conv_id})
    return {"status": "unpinned"}, 200


@api.route("/conversations/<conv_id>/unarchive", methods=["POST"])
@api.output(StatusResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
def unarchive_conversation(user: User, conv_id: str) -> tuple[dict[str, str], int]:
    """Unarchive a conversation (restore to main list)."""
    logger.debug("Unarchiving conversation", extra={"user_id": user.id, "conversation_id": conv_id})
    if not db.unarchive_conversation(conv_id, user.id):
        raise_not_found_error("Conversation")

    logger.info("Conversation unarchived", extra={"user_id": user.id, "conversation_id": conv_id})
    return {"status": "unarchived"}, 200
