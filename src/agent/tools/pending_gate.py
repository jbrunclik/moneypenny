"""Preview now, apply on the user's yes in a later turn.

Shared by the tools that change something lasting from chat (schedule,
edit_standing_chat): the first call stores a preview in a reserved kv
namespace, keyed by conversation, with the turn and request that made it; the
confirm is refused until a newer user message answers it, and only the user's
next message is the answer: a preview left behind expires (a confirm days later
- say from a page the agent read - never applies it). Re-previewing the very
same change keeps its markers (the user already answered exactly that).
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from src.agent.tool_results import get_current_request_id
from src.db.models import db
from src.enums import MessageRole

_MARKERS = frozenset({"turn", "request"})


def latest_user_message_id(conversation_id: str) -> str:
    """The turn marker: production saves each user message before the agent runs."""
    return next(
        (m.id for m in reversed(db.get_messages(conversation_id)) if m.role == MessageRole.USER),
        "",
    )


def keep_pending(
    user_id: str, namespace: str, conversation_id: str, spec: Mapping[str, object]
) -> None:
    """Hold the preview for the user's answer (re-previewing the same change
    keeps its markers, so it stays confirmable)."""
    stored = {
        **spec,
        "turn": latest_user_message_id(conversation_id),
        "request": get_current_request_id() or "",
    }
    if raw := db.kv_get(user_id, namespace, conversation_id):
        previous: dict[str, object] = json.loads(raw)
        if {k: v for k, v in previous.items() if k not in _MARKERS} == {
            k: v for k, v in stored.items() if k not in _MARKERS
        }:
            stored["turn"] = previous["turn"]
            stored["request"] = previous.get("request", "")
    db.kv_set(user_id, namespace, conversation_id, json.dumps(stored))


def unanswered(conversation_id: str, pending: Mapping[str, object]) -> bool:
    """The user has not answered the preview yet: same request, or no newer
    user message (one in the same turn is an interjection, not an answer)."""
    request = get_current_request_id()
    same_turn = bool(request) and request == pending.get("request")
    return same_turn or pending.get("turn") == latest_user_message_id(conversation_id)


def expired(conversation_id: str, pending: Mapping[str, object]) -> bool:
    """More than one user message since the preview: the next one was its
    answer, so the preview is stale."""
    turn = pending.get("turn")
    user_ids = [m.id for m in db.get_messages(conversation_id) if m.role == MessageRole.USER]
    later = user_ids[user_ids.index(turn) + 1 :] if turn in user_ids else user_ids
    return len(later) > 1
