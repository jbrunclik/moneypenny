"""Conversation routes: CRUD, search, sync, messages pagination.

This module handles conversation management including listing, searching,
creating, updating, deleting conversations and messages.
"""

from datetime import datetime
from typing import Any

from apiflask import APIBlueprint
from flask import request

from src.api.errors import raise_not_found_error, raise_validation_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.schemas import (
    ConversationDetailPaginatedResponse,
    ConversationResponse,
    ConversationsListPaginatedResponse,
    CreateConversationRequest,
    MessagesListResponse,
    PaginationDirection,
    SearchResultsResponse,
    StatusResponse,
    SyncResponse,
    UpdateConversationRequest,
)
from src.api.utils import normalize_generated_images
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import User, db
from src.utils.logging import get_logger, log_payload_snippet

logger = get_logger(__name__)

api = APIBlueprint("conversations", __name__, url_prefix="/api", tag="Conversations")


# ============================================================================
# Helper Functions
# ============================================================================


def _optimize_messages_for_response(messages: list[Any]) -> list[dict[str, Any]]:
    """Convert Message objects to optimized response format.

    Only includes file metadata (name, type, messageId, fileIndex), not full data.
    """
    optimized_messages = []
    for m in messages:
        optimized_files = []
        if m.files:
            for idx, file in enumerate(m.files):
                optimized_file = {
                    "name": file.get("name", ""),
                    "type": file.get("type", ""),
                    "messageId": m.id,
                    "fileIndex": idx,
                }
                optimized_files.append(optimized_file)

        msg_data: dict[str, Any] = {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "files": optimized_files,
            "created_at": m.created_at.isoformat(),
        }
        if m.sources:
            msg_data["sources"] = m.sources
        if m.generated_images:
            # Normalize generated_images to ensure proper structure
            # (LLM sometimes returns just strings instead of {"prompt": "..."} objects)
            msg_data["generated_images"] = normalize_generated_images(m.generated_images)
        if m.language:
            msg_data["language"] = m.language

        optimized_messages.append(msg_data)
    return optimized_messages


# ============================================================================
# Conversation Routes
# ============================================================================


@api.route("/conversations", methods=["GET"])
@api.output(ConversationsListPaginatedResponse)
@api.doc(responses=[429])
@rate_limit_conversations
@require_auth
def list_conversations(user: User) -> dict[str, Any]:
    """List conversations for the current user with pagination.

    Query parameters:
    - limit: Number of conversations to return (default: 30, max: 100)
    - cursor: Cursor from previous page for fetching next page

    Returns paginated conversations with message_count for proper sync initialization.
    """
    # Parse pagination parameters
    limit_param = request.args.get("limit")
    cursor_param = request.args.get("cursor")

    # Validate and clamp limit
    if limit_param:
        try:
            limit = int(limit_param)
            limit = max(1, min(limit, Config.CONVERSATIONS_MAX_PAGE_SIZE))
        except ValueError:
            limit = Config.CONVERSATIONS_DEFAULT_PAGE_SIZE
    else:
        limit = Config.CONVERSATIONS_DEFAULT_PAGE_SIZE

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

    return {
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "model": c.model,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
                "message_count": message_count,
            }
            for c, message_count in conv_with_counts
        ],
        "pagination": {
            "next_cursor": next_cursor,
            "has_more": has_more,
            "total_count": total_count,
        },
    }


@api.route("/search", methods=["GET"])
@api.output(SearchResultsResponse)
@api.doc(responses=[400, 429])
@rate_limit_conversations
@require_auth
def search_conversations(user: User) -> dict[str, Any]:
    """Search across all conversations and messages.

    Uses full-text search with BM25 ranking. Searches both conversation
    titles and message content. Results are ordered by relevance.

    Query parameters:
    - q: Search query (required, 1-200 characters)
    - limit: Number of results to return (default: 20, max: 50)
    - offset: Number of results to skip for pagination (default: 0)

    Returns:
    - results: Array of search results with conversation info and message snippets
    - total: Total number of matching results
    - query: The search query that was executed
    """
    query = request.args.get("q", "").strip()

    # Validate query
    if not query:
        raise_validation_error("Search query is required", field="q")
    if len(query) > Config.SEARCH_MAX_QUERY_LENGTH:
        raise_validation_error(
            f"Search query too long (max {Config.SEARCH_MAX_QUERY_LENGTH} characters)",
            field="q",
        )

    # Parse pagination parameters
    try:
        limit = min(int(request.args.get("limit", 20)), Config.SEARCH_MAX_LIMIT)
        limit = max(1, limit)
    except ValueError:
        limit = 20

    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        offset = 0

    logger.debug(
        "Search request",
        extra={"user_id": user.id, "query": query, "limit": limit, "offset": offset},
    )

    results, total = db.search(user.id, query, limit=limit, offset=offset)

    logger.info(
        "Search completed",
        extra={"user_id": user.id, "query": query, "results": len(results), "total": total},
    )

    return {
        "results": [
            {
                "conversation_id": r.conversation_id,
                "conversation_title": r.conversation_title,
                "message_id": r.message_id,
                "message_snippet": r.message_content,
                "match_type": r.match_type,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in results
        ],
        "total": total,
        "query": query,
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
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
    }, 201


@api.route("/conversations/<conv_id>", methods=["GET"])
@api.output(ConversationDetailPaginatedResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
def get_conversation(user: User, conv_id: str) -> tuple[dict[str, Any], int]:
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
    # Parse message pagination parameters
    limit_param = request.args.get("message_limit")
    cursor_param = request.args.get("message_cursor")
    direction_param = request.args.get("direction", PaginationDirection.OLDER.value)

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
    optimized_messages = _optimize_messages_for_response(messages)

    return {
        "id": conv.id,
        "title": conv.title,
        "model": conv.model,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "messages": optimized_messages,
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


@api.route("/conversations/<conv_id>", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
def delete_conversation(user: User, conv_id: str) -> tuple[dict[str, str], int]:
    """Delete a conversation."""
    logger.debug("Deleting conversation", extra={"user_id": user.id, "conversation_id": conv_id})
    if not db.delete_conversation(conv_id, user.id):
        logger.warning(
            "Conversation not found for deletion",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        raise_not_found_error("Conversation")

    logger.info("Conversation deleted", extra={"user_id": user.id, "conversation_id": conv_id})
    return {"status": "deleted"}, 200


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
        # Load messages around the target message (for search result navigation)
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
        messages, pagination = result
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
    optimized_messages = _optimize_messages_for_response(messages)

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


@api.route("/conversations/sync", methods=["GET"])
@api.output(SyncResponse)
@api.doc(responses=[429])
@rate_limit_conversations
@require_auth
def sync_conversations(user: User) -> dict[str, Any]:
    """Sync conversations - returns conversations updated since a given timestamp.

    Query parameters:
    - since: ISO timestamp to get conversations updated after this time (optional)
    - full: If "true", returns all conversations for delete detection (optional)

    Returns:
    - conversations: List of conversation objects with message_count
    - server_time: Current server timestamp to use for next sync
    - is_full_sync: Whether this was a full sync (all conversations returned)
    """
    since_param = request.args.get("since")
    full_param = request.args.get("full", "false").lower() == "true"

    logger.debug(
        "Sync conversations request",
        extra={"user_id": user.id, "since": since_param, "full": full_param},
    )

    # Determine if this is a full sync or incremental
    is_full_sync = full_param or since_param is None

    if is_full_sync:
        # Full sync: get all conversations with message counts
        conv_with_counts = db.list_conversations_with_message_count(user.id)
    else:
        # Incremental sync: only get conversations updated since timestamp
        try:
            since_dt = datetime.fromisoformat(since_param)  # type: ignore[arg-type]
        except ValueError:
            raise_validation_error(
                "Invalid timestamp format. Use ISO format (e.g., 2024-01-01T12:00:00)",
                field="since",
            )
        conv_with_counts = db.get_conversations_updated_since(user.id, since_dt)

    server_time = datetime.now()

    logger.info(
        "Sync conversations completed",
        extra={
            "user_id": user.id,
            "is_full_sync": is_full_sync,
            "conversation_count": len(conv_with_counts),
        },
    )

    return {
        "conversations": [
            {
                "id": conv.id,
                "title": conv.title,
                "model": conv.model,
                "updated_at": conv.updated_at.isoformat(),
                "message_count": message_count,
            }
            for conv, message_count in conv_with_counts
        ],
        "server_time": server_time.isoformat(),
        "is_full_sync": is_full_sync,
    }
