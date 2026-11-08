"""When the background memory review runs, and what it leaves behind.

Called after every saved chat turn (chat_save.py). Per chat, kv_store keeps a
turn counter and a review cursor (the last message a pass reviewed). Every
MEMORY_REVIEW_EVERY_TURNS turns a daemon thread reviews the messages after the
cursor (agent/memory_review.py), labels the triggering reply with what it
saved, adds the pass's cost to that reply and moves the cursor. A turn that
called manage_memory resets the counter but not the cursor: the next pass still
reads the turns before it. A failed pass leaves the cursor, so the next retries.
Agent runs never come through here (the executor saves its own turns).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage

from src.agent.memory_review import ReviewResult, format_note, review_messages
from src.config import Config
from src.db.models import db
from src.db.models.dataclasses import Message
from src.services.costs import calculate_token_cost
from src.utils.logging import get_logger

logger = get_logger(__name__)

KV_NAMESPACE = "memory_review"

# Conversations with a pass in flight
# per-worker: a second worker can at worst run one duplicate pass, whose writes
# go through the same guards (a duplicate add is skipped as already known)
_running: set[str] = set()
_running_lock = threading.Lock()


@dataclass
class _State:
    turns: int = 0
    cursor: str | None = None


def _load(user_id: str, conv_id: str) -> _State:
    raw = db.kv_get(user_id, KV_NAMESPACE, conv_id)
    if not raw:
        return _State()
    data = json.loads(raw)
    return _State(turns=int(data.get("turns", 0)), cursor=data.get("cursor"))


def _save(user_id: str, conv_id: str, state: _State) -> None:
    value = json.dumps({"turns": state.turns, "cursor": state.cursor})
    db.kv_set(user_id, KV_NAMESPACE, conv_id, value)


def _start(fn: Callable[[], None]) -> None:
    """Run a pass off the request path (a seam: tests run it inline)."""
    threading.Thread(target=fn, name="memory-review", daemon=True).start()


def _called_manage_memory(result_messages: list[BaseMessage]) -> bool:
    return any(
        call.get("name") == "manage_memory"
        for message in result_messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    )


def _eligible(conv_id: str, user_id: str) -> bool:
    if not Config.MEMORY_REVIEW_ENABLED:
        return False
    conv = db.get_conversation(conv_id, user_id)
    return conv is not None and not conv.anonymous_mode and not conv.is_planning


def note_turn(
    conv_id: str, user_id: str, message_id: str, result_messages: list[BaseMessage]
) -> None:
    """Count a saved turn; start a review pass when one is due. Never raises."""
    try:
        _note_turn(conv_id, user_id, message_id, result_messages)
    except Exception:
        logger.warning("Memory review trigger failed", exc_info=True)


def _note_turn(
    conv_id: str, user_id: str, message_id: str, result_messages: list[BaseMessage]
) -> None:
    if not _eligible(conv_id, user_id):
        return
    state = _load(user_id, conv_id)
    if _called_manage_memory(result_messages):
        state.turns = 0  # the agent just curated memory itself
        _save(user_id, conv_id, state)
        return
    state.turns += 1
    due = state.turns >= Config.MEMORY_REVIEW_EVERY_TURNS
    if due:
        state.turns = 0
    _save(user_id, conv_id, state)
    if not due:
        return
    with _running_lock:
        if conv_id in _running:
            return
        _running.add(conv_id)
    cursor = state.cursor
    _start(lambda: _run_pass(conv_id, user_id, message_id, cursor))


def messages_to_review(conv_id: str, cursor: str | None) -> list[Message]:
    """Messages after the cursor, from at most MEMORY_REVIEW_MAX_TURNS user turns back."""
    messages = db.get_messages(conv_id)
    ids = [m.id for m in messages]
    if cursor in ids:
        messages = messages[ids.index(cursor) + 1 :]
    user_starts = [i for i, m in enumerate(messages) if m.role == "user"]
    if len(user_starts) > Config.MEMORY_REVIEW_MAX_TURNS:
        skipped = user_starts[-Config.MEMORY_REVIEW_MAX_TURNS]
        logger.info(
            "Memory review window capped",
            extra={"conversation_id": conv_id, "skipped_messages": skipped},
        )
        messages = messages[skipped:]
    return messages


def _run_pass(conv_id: str, user_id: str, message_id: str, cursor: str | None) -> None:
    try:
        messages = messages_to_review(conv_id, cursor)
        if not messages:
            return
        result = review_messages(user_id, conv_id, messages)
        if result.applied:
            db.set_memory_note(message_id, format_note(result.applied))
        cost = _record_cost(message_id, result)
        state = _load(user_id, conv_id)  # turns may have moved on meanwhile
        state.cursor = messages[-1].id
        _save(user_id, conv_id, state)
        logger.info(
            "Memory review pass",
            extra={
                "user_id": user_id,
                "conversation_id": conv_id,
                "reviewed_messages": len(messages),
                "applied": len(result.applied),
                "cost_usd": round(cost, 6),
            },
        )
    except Exception:
        logger.warning(
            "Memory review pass failed",
            extra={"user_id": user_id, "conversation_id": conv_id},
            exc_info=True,
        )
    finally:
        with _running_lock:
            _running.discard(conv_id)


def _record_cost(message_id: str, result: ReviewResult) -> float:
    cost = calculate_token_cost(Config.AI_ASSIST_MODEL, result.input_tokens, result.output_tokens)
    try:
        db.add_message_cost_usd(message_id, cost)
    except Exception:  # the memories landed: a lost cost row is not a failed pass
        logger.warning("Memory review cost not recorded", exc_info=True)
    return cost
