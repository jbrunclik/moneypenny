"""Conversation trash routes: list, restore, permanent delete, empty, bulk trash/restore.

Attached to conversations.api (one shared "Conversations" blueprint keeps a
single OpenAPI tag). DELETE /conversations/<id> itself (move to trash) lives
in conversations.py.
"""

from datetime import datetime, timedelta
from typing import Any

from src.api.errors import raise_not_found_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.routes.conversations import api
from src.api.schemas.common import StatusResponse
from src.api.schemas.conversations import (
    BulkRestoreRequest,
    BulkRestoreResponse,
    BulkTrashRequest,
    BulkTrashResponse,
    ConversationsListPaginatedResponse,
    ConversationsPageQuery,
    EmptyTrashResponse,
)
from src.api.validation import validate_query, validate_request
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import Conversation, User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _trashed_item(c: Conversation, message_count: int, preview: str | None) -> dict[str, Any]:
    """Trash listing row; purge_at is computed here so clients never need the retention setting."""
    retention = timedelta(days=Config.TRASH_RETENTION_DAYS)
    return {
        "id": c.id,
        "title": c.title,
        "model": c.model,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
        "message_count": message_count,
        "archived": c.archived,
        "pinned": c.pinned,
        "last_message_preview": preview,
        "deleted_at": c.deleted_at.isoformat() if c.deleted_at else None,
        "purge_at": (c.deleted_at + retention).isoformat() if c.deleted_at else None,
    }


@api.route("/conversations/trash", methods=["GET"])
@api.output(ConversationsListPaginatedResponse)
@api.doc(responses=[429])
@rate_limit_conversations
@require_auth
@validate_query(ConversationsPageQuery)
def list_trashed_conversations(user: User, query: ConversationsPageQuery) -> dict[str, Any]:
    """List conversations in the trash, most recently deleted first."""
    rows, next_cursor, has_more, total_count = db.list_trashed_conversations_paginated(
        user.id, limit=query.limit, cursor=query.cursor
    )
    return {
        "conversations": [_trashed_item(*row) for row in rows],
        "pagination": {
            "next_cursor": next_cursor,
            "has_more": has_more,
            "total_count": total_count,
        },
    }


@api.route("/conversations/trash", methods=["DELETE"])
@api.output(EmptyTrashResponse)
@api.doc(responses=[429])
@rate_limit_conversations
@require_auth
def empty_trash(user: User) -> dict[str, int]:
    """Permanently delete every conversation in the trash."""
    deleted = db.empty_trash(user.id)
    logger.info("Trash emptied", extra={"user_id": user.id, "deleted": deleted})
    return {"deleted": deleted}


@api.route("/conversations/<conv_id>/restore", methods=["POST"])
@api.output(StatusResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
def restore_conversation(user: User, conv_id: str) -> tuple[dict[str, str], int]:
    """Restore a conversation from the trash (back to the list or archive it was in)."""
    if not db.restore_conversation(conv_id, user.id):
        raise_not_found_error("Conversation")
    logger.info("Conversation restored", extra={"user_id": user.id, "conversation_id": conv_id})
    return {"status": "restored"}, 200


@api.route("/conversations/<conv_id>/permanent", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[404, 429])
@rate_limit_conversations
@require_auth
def delete_conversation_permanently(user: User, conv_id: str) -> tuple[dict[str, str], int]:
    """Permanently delete a conversation that is in the trash."""
    if not db.delete_trashed_conversation(conv_id, user.id):
        raise_not_found_error("Conversation")
    logger.info(
        "Conversation permanently deleted",
        extra={"user_id": user.id, "conversation_id": conv_id},
    )
    return {"status": "deleted"}, 200


def _naive_local(moment: datetime) -> datetime:
    """Conversation timestamps are stored as naive local time (datetime.now());
    the browser sends UTC. Compare like with like."""
    if moment.tzinfo is None:
        return moment
    return moment.astimezone().replace(tzinfo=None)


@api.route("/conversations/bulk-trash", methods=["POST"])
@api.output(BulkTrashResponse)
@api.doc(responses=[400, 429])
@rate_limit_conversations
@require_auth
@validate_request(BulkTrashRequest)
def bulk_trash_conversations(user: User, data: BulkTrashRequest) -> dict[str, list[str]]:
    """Move many conversations to the trash in one transaction (bulk delete)."""
    # The schema guarantees created_before with all; the check narrows the type
    if data.all and data.created_before is not None:
        trashed = db.trash_all_conversations(
            user.id,
            exclude_ids=data.exclude_ids,
            created_before=_naive_local(data.created_before),
            extra_ids=data.ids,
        )
    else:
        trashed = db.trash_conversations(user.id, data.ids)
    logger.info(
        "Conversations bulk trashed",
        extra={"user_id": user.id, "count": len(trashed), "mode": "all" if data.all else "ids"},
    )
    return {"trashed_ids": trashed}


@api.route("/conversations/bulk-restore", methods=["POST"])
@api.output(BulkRestoreResponse)
@api.doc(responses=[400, 429])
@rate_limit_conversations
@require_auth
@validate_request(BulkRestoreRequest)
def bulk_restore_conversations(user: User, data: BulkRestoreRequest) -> dict[str, list[str]]:
    """Restore many conversations from the trash (Undo of a bulk delete)."""
    restored = db.restore_conversations(user.id, data.ids)
    logger.info(
        "Conversations bulk restored",
        extra={"user_id": user.id, "count": len(restored), "mode": "restore"},
    )
    return {"restored_ids": restored}
