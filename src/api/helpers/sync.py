"""Cross-device sync payloads: conversation summaries and the cursor sync."""

from typing import Any

from src.config import Config
from src.db.models import Conversation, db


def is_chat_conversation(conv: Conversation) -> bool:
    """Regular chats only - planner, agents and programs have their own syncs."""
    return not (conv.is_planning or conv.is_agent or conv.is_sports or conv.is_language)


def sync_summary(
    conv: Conversation,
    message_count: int,
    preview: str | None,
    last_message_id: str | None = None,
) -> dict[str, Any]:
    """One conversation as the sync endpoint returns it."""
    return {
        "id": conv.id,
        "title": conv.title,
        "model": conv.model,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "message_count": message_count,
        "last_message_preview": preview,
        "last_message_id": last_message_id,
        "archived": conv.archived,
        "trashed": conv.deleted_at is not None,
        "pinned": conv.pinned,
    }


def cursor_sync(user_id: str, cursor: int) -> dict[str, Any]:
    """Chat conversations changed after `cursor`, with their state.

    Non-chat changes still advance the returned cursor (nothing to re-send).
    A permanently deleted conversation is reported by id in removed_ids.
    """
    page_size = Config.SYNC_CHANGES_PAGE_SIZE
    changes = db.get_conversation_changes(user_id, cursor, page_size + 1)
    has_more = len(changes) > page_size
    changes = changes[:page_size]

    conversations = [
        sync_summary(c.conversation, c.message_count, c.last_message_preview, c.last_message_id)
        for c in changes
        if c.conversation is not None and is_chat_conversation(c.conversation)
    ]
    return {
        "conversations": conversations,
        "removed_ids": [c.conversation_id for c in changes if c.conversation is None],
        "cursor": changes[-1].seq if changes else cursor,
        "has_more": has_more,
        "is_full_sync": False,
    }
