"""When the background memory review runs, and what it leaves behind.

Called after every saved chat turn (chat_save.py). Per chat, kv_store keeps a
turn counter (key "<conv>:turns", bumped atomically) and, separately, a review
cursor (key "<conv>": the last message a pass reviewed). Separate keys because
two workers write them: a turn only touches the counter, a pass only the
cursor. Every MEMORY_REVIEW_EVERY_TURNS turns a daemon thread reviews the
messages after the cursor, up to the triggering reply
(agent/memory_review.py), labels that reply with what it saved, adds the
pass's cost to it and moves the cursor. A turn that called manage_memory
resets the counter but not the cursor: the next pass still reads the turns
before it. A failed pass leaves the cursor, so the next retries. Agent runs
never come through here (the executor saves its own turns).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage

from src.agent.memory_review import format_note, review_messages
from src.config import Config
from src.db.models import db
from src.db.models.dataclasses import Message
from src.db.models.timestamps import from_db, to_db
from src.services.costs import calculate_token_cost
from src.utils.logging import get_logger

logger = get_logger(__name__)

KV_NAMESPACE = "memory_review"

# Conversations with a pass in flight
# per-worker: a second worker can at worst run one duplicate pass, whose writes
# go through the same guards (an add the bank already holds is skipped)
_running: set[str] = set()
_running_lock = threading.Lock()


@dataclass
class _Cursor:
    message_id: str | None = None
    # The cursor message's time: a regenerate deletes that message, and the
    # next pass then starts after this time instead of from the beginning
    at: str | None = None


@dataclass
class _Window:
    """What one pass reviews: after the cursor, up to the triggering reply."""

    cursor: _Cursor
    until_id: str
    # The trigger's time: if a regenerate deletes it, the window still ends there
    until_at: str | None


def _turns_key(conv_id: str) -> str:
    return f"{conv_id}:turns"


def _load_cursor(user_id: str, conv_id: str) -> _Cursor:
    raw = db.kv_get(user_id, KV_NAMESPACE, conv_id)
    if not raw:
        return _Cursor()
    data = json.loads(raw)  # a record from before the split also holds "turns"
    return _Cursor(message_id=data.get("cursor"), at=data.get("cursor_at"))


def _save_cursor(user_id: str, conv_id: str, cursor: _Cursor) -> None:
    value = json.dumps({"cursor": cursor.message_id, "cursor_at": cursor.at})
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
    # Agent chats are out: runs save their trigger - which can carry another
    # agent's model-written text - as user messages, never a memory source
    return (
        conv is not None and not conv.anonymous_mode and not conv.is_planning and not conv.is_agent
    )


def note_turn(
    conv_id: str, user_id: str, message_id: str, result_messages: list[BaseMessage]
) -> None:
    """Count a saved turn; start a review pass when one is due. Never raises."""
    try:
        _note_turn(conv_id, user_id, message_id, result_messages)
    except Exception:
        logger.warning(
            "Memory review trigger failed",
            extra={"user_id": user_id, "conversation_id": conv_id},
            exc_info=True,
        )


def _note_turn(
    conv_id: str, user_id: str, message_id: str, result_messages: list[BaseMessage]
) -> None:
    if not _eligible(conv_id, user_id):
        return
    if _called_manage_memory(result_messages):
        # The agent just curated memory itself
        db.kv_set(user_id, KV_NAMESPACE, _turns_key(conv_id), "0")
        return
    turns = db.kv_increment(user_id, KV_NAMESPACE, _turns_key(conv_id))
    # Exactly one turn hits each multiple, whichever worker counts it
    if turns % Config.MEMORY_REVIEW_EVERY_TURNS != 0:
        return
    # Read before claiming the chat: a raise after the claim would leave it
    # claimed for the life of the worker
    trigger = db.get_message_by_id(message_id)
    window = _Window(
        cursor=_load_cursor(user_id, conv_id),
        until_id=message_id,
        until_at=to_db(trigger.created_at) if trigger else None,
    )
    with _running_lock:
        if conv_id in _running:
            return
        _running.add(conv_id)
    _start(lambda: _run_pass(conv_id, user_id, window))


def _bounded(messages: list[Message], window: _Window) -> list[Message]:
    """Cut to after the cursor and up to the trigger (never a turn in flight)."""
    ids = [m.id for m in messages]
    if window.until_id in ids:
        messages = messages[: ids.index(window.until_id) + 1]
    elif window.until_at is not None:  # the trigger is gone (regenerated)
        until = from_db(window.until_at)
        messages = [m for m in messages if m.created_at <= until]
    ids = [m.id for m in messages]
    cursor = window.cursor
    if cursor.message_id in ids:
        return messages[ids.index(cursor.message_id) + 1 :]
    if cursor.at is not None:  # the cursor message is gone (regenerated)
        after = from_db(cursor.at)
        return [m for m in messages if m.created_at > after]
    return messages


def messages_to_review(conv_id: str, window: _Window) -> list[Message]:
    """The window's messages, from at most MEMORY_REVIEW_MAX_TURNS user turns back."""
    messages = _bounded(db.get_messages(conv_id), window)
    user_starts = [i for i, m in enumerate(messages) if m.role == "user"]
    if len(user_starts) > Config.MEMORY_REVIEW_MAX_TURNS:
        skipped = user_starts[-Config.MEMORY_REVIEW_MAX_TURNS]
        logger.info(
            "Memory review window capped",
            extra={"conversation_id": conv_id, "skipped_messages": skipped},
        )
        messages = messages[skipped:]
    return messages


def _note_target(conv_id: str, window: _Window) -> str | None:
    """The reply that carries the note and cost: the trigger, or the reply
    that replaced it when the user regenerated mid-pass."""
    if db.get_message_by_id(window.until_id) is not None:
        return window.until_id
    if window.until_at is None:
        return None
    until = from_db(window.until_at)
    return next(
        (m.id for m in db.get_messages(conv_id) if m.role == "assistant" and m.created_at > until),
        None,
    )


def _run_pass(conv_id: str, user_id: str, window: _Window) -> None:
    try:
        messages = messages_to_review(conv_id, window)
        if not messages:
            return
        result = review_messages(user_id, conv_id, messages)
        target = _note_target(conv_id, window)
        cost = calculate_token_cost(
            Config.AI_ASSIST_MODEL, result.input_tokens, result.output_tokens
        )
        if target is not None:
            if result.applied:
                db.set_memory_note(target, format_note(result.applied))
            _record_cost(target, cost)
        last = messages[-1]
        _save_cursor(user_id, conv_id, _Cursor(last.id, to_db(last.created_at)))
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


def _record_cost(message_id: str, cost: float) -> None:
    try:
        db.add_message_cost_usd(message_id, cost)
    except Exception:  # the memories landed: a lost cost row is not a failed pass
        logger.warning("Memory review cost not recorded", exc_info=True)
