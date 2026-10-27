"""Conversation routes: list, CRUD, anonymous mode, sync.

Owns the shared "Conversations" blueprint. Search lives in
conversation_search.py, archive/pin in conversation_organize.py and message
endpoints in conversation_messages.py; those attach their routes to this
blueprint.
"""

from typing import Any

from apiflask import APIBlueprint

from src.api.errors import raise_not_found_error, raise_validation_error
from src.api.helpers.sync import cursor_sync, sync_summary
from src.api.helpers.turn_steering import has_lost_reply, running_turn_id
from src.api.rate_limiting import rate_limit_conversations
from src.api.schemas.common import StatusResponse
from src.api.schemas.conversations import (
    ConversationDetailPaginatedResponse,
    ConversationDetailQuery,
    ConversationResponse,
    ConversationsListPaginatedResponse,
    ConversationsPageQuery,
    CreateConversationRequest,
    SyncQuery,
    SyncResponse,
    UpdateAnonymousModeRequest,
    UpdateConversationRequest,
)
from src.api.utils import serialize_messages_for_response
from src.api.validation import validate_query, validate_request
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import User, db
from src.utils.clock import to_api, utc_now
from src.utils.logging import get_logger, log_payload_snippet

logger = get_logger(__name__)

api = APIBlueprint("conversations", __name__, url_prefix="/api", tag="Conversations")


@api.route("/conversations", methods=["GET"])
@api.output(ConversationsListPaginatedResponse)
@api.doc(responses=[429])
@rate_limit_conversations
@require_auth
@validate_query(ConversationsPageQuery)
def list_conversations(user: User, query: ConversationsPageQuery) -> dict[str, Any]:
    """List conversations for the current user with pagination.

    Query parameters:
    - limit: Number of conversations to return (default: 30, max: 100)
    - cursor: Cursor from previous page for fetching next page

    Returns paginated conversations with message_count for proper sync initialization.
    """
    limit, cursor_param = query.limit, query.cursor

    logger.debug(
        "Listing conversations",
        extra={"user_id": user.id, "limit": limit, "cursor": cursor_param},
    )

    # Get paginated results with message counts in a single efficient query
    conv_with_counts, next_cursor, has_more, total_count = (
        db.list_conversations_paginated_with_counts(user.id, limit=limit, cursor=cursor_param)
    )

    logger.info(
        "Conversations listed",
        extra={
            "user_id": user.id,
            "returned": len(conv_with_counts),
            "total": total_count,
            "has_more": has_more,
        },
    )

    pinned_with_counts = db.list_pinned_conversations(user.id)

    def _conv_payload(c: Any, message_count: int, preview: str | None) -> dict[str, Any]:
        return {
            "id": c.id,
            "title": c.title,
            "model": c.model,
            "created_at": to_api(c.created_at),
            "updated_at": to_api(c.updated_at),
            "message_count": message_count,
            "read_count": c.read_message_count,
            "archived": c.archived or None,
            "pinned": c.pinned or None,
            "last_message_preview": preview,
        }

    return {
        "conversations": [
            _conv_payload(c, message_count, preview)
            for c, message_count, preview in conv_with_counts
        ],
        "pinned_conversations": [
            _conv_payload(c, message_count, preview)
            for c, message_count, preview in pinned_with_counts
        ],
        "pagination": {
            "next_cursor": next_cursor,
            "has_more": has_more,
            "total_count": total_count,
        },
    }


@api.route("/conversations", methods=["POST"])
@api.output(ConversationResponse, status_code=201)
@api.doc(responses=[429])
@rate_limit_conversations
@require_auth
@validate_request(CreateConversationRequest)
def create_conversation(user: User, data: CreateConversationRequest) -> tuple[dict[str, str], int]:
    """Create a new conversation."""
    model = data.model or Config.DEFAULT_MODEL
    log_payload_snippet(logger, {"model": model})

    logger.debug("Creating conversation", extra={"user_id": user.id, "model": model})
    conv = db.create_conversation(user.id, model=model)
    logger.info(
        "Conversation created",
        extra={"user_id": user.id, "conversation_id": conv.id, "model": model},
    )
    return {
        "id": conv.id,
        "title": conv.title,
        "model": conv.model,
        "created_at": to_api(conv.created_at),
        "updated_at": to_api(conv.updated_at),
    }, 201


@api.route("/conversations/<conv_id>", methods=["GET"])
@api.output(ConversationDetailPaginatedResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
@validate_query(ConversationDetailQuery)
def get_conversation(
    user: User, query: ConversationDetailQuery, conv_id: str
) -> tuple[dict[str, Any], int]:
    """Get a conversation with its messages (paginated).

    Query parameters for message pagination:
    - message_limit: Number of messages to return (default: 50, max: 200)
    - message_cursor: Cursor for fetching older/newer messages
    - direction: "older" (default) or "newer" for pagination direction

    By default, returns the newest messages.

    Optimized: Only includes file metadata, not thumbnails or full file data.
    Thumbnails are fetched on-demand via /api/messages/<message_id>/files/<file_index>/thumbnail.
    Full files can be fetched via /api/messages/<message_id>/files/<file_index>.
    """
    limit, cursor_param, direction = query.message_limit, query.message_cursor, query.direction

    logger.debug(
        "Getting conversation",
        extra={
            "user_id": user.id,
            "conversation_id": conv_id,
            "message_limit": limit,
            "message_cursor": cursor_param,
            "direction": direction.value,
        },
    )
    conv = db.get_conversation(conv_id, user.id)
    if not conv:
        logger.warning(
            "Conversation not found",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        raise_not_found_error("Conversation")

    # Get paginated messages
    messages, pagination = db.get_messages_paginated(
        conv_id, limit=limit, cursor=cursor_param, direction=direction
    )
    logger.info(
        "Conversation retrieved",
        extra={
            "user_id": user.id,
            "conversation_id": conv_id,
            "message_count": len(messages),
            "total_messages": pagination.total_count,
            "has_older": pagination.has_older,
            "has_newer": pagination.has_newer,
        },
    )

    # Optimize file data: only include metadata, not thumbnails or full file data
    # Thumbnails are fetched on-demand via /api/messages/<message_id>/files/<file_index>/thumbnail
    optimized_messages = serialize_messages_for_response(messages)

    # Check if this is an agent conversation with pending approval
    has_pending_approval = False
    if conv.is_agent and conv.agent_id:
        has_pending_approval = db.has_pending_approval(conv.agent_id)

    return {
        "id": conv.id,
        "title": conv.title,
        "model": conv.model,
        "created_at": to_api(conv.created_at),
        "updated_at": to_api(conv.updated_at),
        "is_agent": conv.is_agent,
        "agent_id": conv.agent_id,
        "has_pending_approval": has_pending_approval,
        "archived": conv.archived,
        "anonymous_mode": conv.anonymous_mode,
        "messages": optimized_messages,
        # Only the newest page holds the turn in flight, and only a live one:
        # a dead worker's placeholder sent every open into a doomed follow
        "streaming_message_id": running_turn_id(conv_id),
        "lost_reply": has_lost_reply(conv_id),
        "message_pagination": {
            "older_cursor": pagination.older_cursor,
            "newer_cursor": pagination.newer_cursor,
            "has_older": pagination.has_older,
            "has_newer": pagination.has_newer,
            "total_count": pagination.total_count,
        },
    }, 200


@api.route("/conversations/<conv_id>", methods=["PATCH"])
@api.output(StatusResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
@validate_request(UpdateConversationRequest)
def update_conversation(
    user: User, data: UpdateConversationRequest, conv_id: str
) -> tuple[dict[str, str], int]:
    """Update a conversation (title, model)."""
    title = data.title
    model = data.model
    log_payload_snippet(logger, {"title": title, "model": model})

    logger.debug(
        "Updating conversation",
        extra={"user_id": user.id, "conversation_id": conv_id, "title": title, "model": model},
    )
    if not db.update_conversation(conv_id, user.id, title=title, model=model):
        logger.warning(
            "Conversation not found for update",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        raise_not_found_error("Conversation")

    logger.info("Conversation updated", extra={"user_id": user.id, "conversation_id": conv_id})
    return {"status": "updated"}, 200


@api.route("/conversations/<conv_id>/anonymous-mode", methods=["PATCH"])
@api.output(StatusResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
@validate_request(UpdateAnonymousModeRequest)
def update_anonymous_mode(
    user: User, data: UpdateAnonymousModeRequest, conv_id: str
) -> tuple[dict[str, str], int]:
    """Turn anonymous mode on or off for a conversation.

    Persisted server-side so the setting survives a page reload - it used to be
    client-only state, which meant a "private" conversation quietly became
    memory-enabled after a refresh.
    """
    if not db.set_conversation_anonymous_mode(conv_id, user.id, data.anonymous_mode):
        logger.warning(
            "Conversation not found for anonymous mode update",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        raise_not_found_error("Conversation")

    logger.info(
        "Anonymous mode updated",
        extra={
            "user_id": user.id,
            "conversation_id": conv_id,
            "anonymous_mode": data.anonymous_mode,
        },
    )
    return {"status": "updated"}, 200


@api.route("/conversations/<conv_id>", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
def delete_conversation(user: User, conv_id: str) -> tuple[dict[str, str], int]:
    """Move a conversation to the trash.

    Agent and program conversations (planner, sports, language) have no
    trash view and are deleted immediately, as before.
    """
    logger.debug("Deleting conversation", extra={"user_id": user.id, "conversation_id": conv_id})
    conv = db.get_conversation(conv_id, user.id)
    if conv and (conv.is_agent or conv.is_planning or conv.is_sports or conv.is_language):
        db.delete_conversation(conv_id, user.id)
        logger.info("Conversation deleted", extra={"user_id": user.id, "conversation_id": conv_id})
        return {"status": "deleted"}, 200

    # get_conversation hides trashed rows; trash_conversation is idempotent,
    # so a retried DELETE of an already-trashed conversation still succeeds
    if not db.trash_conversation(conv_id, user.id):
        logger.warning(
            "Conversation not found for deletion",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        raise_not_found_error("Conversation")

    logger.info("Conversation trashed", extra={"user_id": user.id, "conversation_id": conv_id})
    return {"status": "trashed"}, 200


@api.route("/conversations/sync", methods=["GET"])
@api.output(SyncResponse)
@api.doc(responses=[429])
@rate_limit_conversations
@require_auth
@validate_query(SyncQuery)
def sync_conversations(user: User, query: SyncQuery) -> dict[str, Any]:
    """Sync conversations: every conversation, or the changes after a cursor.

    Query parameters:
    - cursor: change-log position from the last sync - only what changed since
    - full: If "true" (or no cursor), returns all conversations for delete detection

    Returns:
    - conversations: List of conversation objects with message_count
    - server_time: Current server timestamp
    - cursor / removed_ids / has_more: the change-log position and page
    """
    cursor_param, full_param = query.cursor, query.full

    logger.debug(
        "Sync conversations request",
        extra={
            "user_id": user.id,
            "cursor": cursor_param,
            "full": full_param,
        },
    )

    # IMPORTANT: Capture server_time (and the cursor) BEFORE the database query
    # to prevent race conditions. If we capture it after, a conversation
    # created/updated between the query and the capture would be missed and
    # never fetched again (since the client moves past it).
    server_time = to_api(utc_now())
    cursor = db.get_sync_cursor()

    if cursor_param is not None and not full_param:
        # Change-log sync: everything that changed after the client's cursor
        try:
            after = int(cursor_param)
        except ValueError:
            raise_validation_error(
                "Invalid cursor. Use the cursor from the last sync.", field="cursor"
            )
        return {**cursor_sync(user.id, after), "server_time": server_time}

    # Full sync: every conversation with its message count (a client without
    # a cursor yet, or one checking for deletions)
    conv_with_counts = db.list_conversations_with_message_count(user.id)

    logger.info(
        "Sync conversations completed",
        extra={
            "user_id": user.id,
            "conversation_count": len(conv_with_counts),
        },
    )

    return {
        "conversations": [
            sync_summary(conv, message_count, preview)
            for conv, message_count, preview in conv_with_counts
        ],
        "server_time": server_time,
        "cursor": cursor,
        "removed_ids": [],
        "has_more": False,
    }
