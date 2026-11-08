"""Scheduled items as API response data (the chat chip and the Command Center lane)."""

from src.agent.tools.scheduling import describe_ends, describe_when
from src.db.models import db
from src.db.models.dataclasses import ScheduledItem
from src.utils.clock import to_api

_TITLE_MAX_CHARS = 60


def item_to_response(item: ScheduledItem, conversation_title: str) -> dict[str, object]:
    """An item as ScheduledItemResponse data."""
    title = (
        item.text if len(item.text) <= _TITLE_MAX_CHARS else item.text[: _TITLE_MAX_CHARS - 1] + "…"
    )
    return {
        "id": item.id,
        "conversation_id": item.conversation_id,
        "conversation_title": conversation_title,
        "kind": item.kind,
        "title": title,
        "when": describe_when(item),
        "ends": describe_ends(item),
        "status": item.status,
        "next_run_at": to_api(item.next_run_at),
        "standing": item.standing,
        "paused_reason": item.paused_reason,
    }


def items_to_response(user_id: str, items: list[ScheduledItem]) -> list[dict[str, object]]:
    """Items with their chats' titles (one lookup per chat)."""
    titles: dict[str, str] = {}
    for conversation_id in {i.conversation_id for i in items}:
        conv = db.get_conversation(conversation_id, user_id)
        titles[conversation_id] = (conv.title if conv else None) or "Chat"
    return [item_to_response(i, titles[i.conversation_id]) for i in items]
