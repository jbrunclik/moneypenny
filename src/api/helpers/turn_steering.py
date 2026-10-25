"""Steering a turn in flight: the interject route, and a send from another
device while the conversation's turn is still running.

Two devices sending into one conversation at once used to start two parallel
turns whose messages and replies interleaved. A plain text send that arrives
while a turn is live is saved as steering for that turn instead (as the
sending device's own second send would be), so the running reply takes it
into account and the conversation keeps one reply per turn.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

from src.agent.interjection import save_interjection
from src.api.schemas.chat import ChatRequest
from src.api.utils import is_empty_placeholder, streaming_message_id
from src.config import Config
from src.db.models import Message, db
from src.enums import MessageRole
from src.utils.logging import get_logger

logger = get_logger(__name__)

# How often a batch send that steered polls for the running turn's reply
_REPLY_POLL_INTERVAL_SECONDS = 0.5


def running_turn_id(conv_id: str) -> str | None:
    """The reply a LIVE turn is generating in this conversation, if any.

    An empty placeholder alone isn't proof - a turn whose worker died keeps
    one until the cutoff. Live means its journal has no end marker and moved
    recently (the resume endpoint's stall rule), or - nothing journaled yet,
    or the journal is off - the placeholder itself is that recent.
    """
    placeholder_id = streaming_message_id(conv_id)
    if placeholder_id is None:
        return None
    stall = Config.STREAM_RESUME_STALL_SECONDS
    last = db.journal_last_event(placeholder_id)
    if last is not None:
        event, recorded_at = last
        if json.loads(event).get("type") == "stream_end":
            return None
        return placeholder_id if time.time() - recorded_at < stall else None
    placeholder = db.get_message_by_id(placeholder_id)
    if placeholder is None or datetime.now() - placeholder.created_at >= timedelta(seconds=stall):
        return None
    return placeholder_id


def mark_turn_in_flight(conv_id: str) -> str | None:
    """Save a batch turn's empty reply now, as a stream saves its placeholder.

    Oct 2026: a batch turn left no trace while it ran, so sends from the
    phone during a ~170 s stall each started a parallel turn, and its reply -
    inserted at the end - landed after all of them. The placeholder makes the
    turn steerable (running_turn_id), lets other devices follow it, and keeps
    the reply under its question. None when it cannot be saved: the turn then
    runs untracked and its reply is inserted at the end, as before.
    """
    try:
        return db.add_message(conv_id, MessageRole.ASSISTANT, "").id
    except Exception:
        logger.warning(
            "Failed to save batch placeholder", extra={"conversation_id": conv_id}, exc_info=True
        )
        return None


def discard_unused_placeholder(message_id: str | None) -> None:
    """Delete a failed turn's empty reply (a chat must not end on an empty row)."""
    if message_id is None:
        return
    try:
        db.delete_message_by_id(message_id)
    except Exception:
        logger.warning(
            "Failed to delete unused placeholder message",
            extra={"message_id": message_id},
            exc_info=True,
        )


def _is_dead_placeholder(message: Message) -> bool:
    """An empty reply no turn will fill: its worker died mid-turn.

    Proof is its age past the longest a turn runs, or a journal that stalled
    without an end marker (the resume endpoint's rule). A reply with no
    journal - a batch turn's - may still be running past the stall window.
    """
    longest = max(Config.CHAT_TIMEOUT, Config.DEEP_RESEARCH_RUN_TIMEOUT_SECONDS) + 60
    if datetime.now() - message.created_at > timedelta(seconds=longest):
        return True
    last = db.journal_last_event(message.id)
    if last is None:
        return False
    event, recorded_at = last
    return (
        json.loads(event).get("type") != "stream_end"
        and time.time() - recorded_at >= Config.STREAM_RESUME_STALL_SECONDS
    )


def _dead_placeholders(conv_id: str) -> list[Message]:
    """The conversation's empty replies left by killed workers.

    Only the tail is scanned: steering saved after a placeholder sits
    behind it.
    """
    return [
        m
        for m in db.get_messages(conv_id)[-3:]
        if is_empty_placeholder(m) and _is_dead_placeholder(m)
    ]


def has_lost_reply(conv_id: str) -> bool:
    """Whether the conversation's last turn died with nothing saved.

    Its empty reply is filtered from responses, so a chat opened after the
    turn died ended on the question with no word; the client offers the
    retry from this.
    """
    return bool(_dead_placeholders(conv_id))


def discard_dead_placeholders(conv_id: str) -> None:
    """Delete empty replies a killed worker left behind, before a new turn.

    Oct 2026: a restart killed a turn mid-stream. Its empty reply - hidden
    by the UI - blocked the regenerate (the chat no longer ended on the
    user's message) and went into every later turn's history.
    """
    for message in _dead_placeholders(conv_id):
        logger.info(
            "Discarding a dead turn's empty reply",
            extra={"conversation_id": conv_id, "message_id": message.id},
        )
        discard_unused_placeholder(message.id)


def can_steer(data: ChatRequest) -> bool:
    """Whether a send can become steering: plain text the agent reads mid-turn.

    Attachments, forced tools, re-runs, deep research and app actions need a
    turn of their own (and their own reply).
    """
    return bool(
        data.message.strip()
        and not data.files
        and not data.force_tools
        and data.rerun_mode is None
        and data.deep_research is None
        and data.action is None
    )


def steer_running_turn(
    user_id: str, conv_id: str, text: str, client_message_id: str | None
) -> Message:
    """Save `text` as steering for the conversation's turn in flight.

    Persisted as a visible user message FIRST - even if the running turn
    never consumes it (already answering), the guidance is in history for
    the next turn. Saved under the id of the bubble the client rendered
    (sync echoes and later deletes then find it).
    """
    steering = db.add_message(conv_id, MessageRole.USER, text, message_id=client_message_id)
    _order_reply_after_steering(conv_id, steering)
    save_interjection(user_id, conv_id, text)
    logger.info(
        "Interjection accepted",
        extra={"user_id": user_id, "conversation_id": conv_id, "length": len(text)},
    )
    return steering


def _order_reply_after_steering(conv_id: str, steering: Message) -> None:
    """Keep the in-flight reply AFTER the steering it takes into account.

    The reply's placeholder was saved at turn start, so the steering would
    otherwise sort after it and the turn would end on a user message - no
    regenerate/continue on the reply (continue requires an assistant last),
    live and after a reload. A turn that already finished has no
    placeholder: the steering stays last, for the next turn.
    """
    placeholder = next(
        (m for m in reversed(db.get_messages(conv_id)[-3:]) if is_empty_placeholder(m)), None
    )
    if placeholder is not None:
        db.set_message_created_at(placeholder.id, steering.created_at + timedelta(microseconds=1))


def wait_for_reply(message_id: str) -> Message | None:
    """The steered turn's reply once saved (a batch send answers with it).

    None when the turn ends without one (removed, or still empty when its
    stream stalls) or runs past the chat timeout.
    """
    deadline = time.monotonic() + Config.CHAT_TIMEOUT
    while time.monotonic() < deadline:
        reply = db.get_message_by_id(message_id)
        if reply is None:
            return None
        if not is_empty_placeholder(reply):
            return reply
        if running_turn_id(reply.conversation_id) != message_id:
            return None
        time.sleep(_REPLY_POLL_INTERVAL_SECONDS)
    return None


def defer_unanswered_steering(conv_id: str, reply_id: str, text: str | None) -> str | None:
    """Move steering the turn never read after its reply; its id, or None.

    Steering is read only between tool rounds, so one sent while the final
    answer was writing sat ABOVE a reply that ignored it, and nothing ever
    answered it. After the reply, the chat ends on it: the client's
    follow-up turn (a regenerate, which answers the last user message)
    replies to it. `text` is the turn's unconsumed interjection.
    """
    if not text:
        return None
    reply = db.get_message_by_id(reply_id)
    if reply is None:
        return None
    earlier = [m for m in db.get_messages(conv_id) if m.created_at < reply.created_at]
    steering = next(
        (m for m in reversed(earlier) if m.role == MessageRole.USER and m.content == text), None
    )
    if steering is None:
        return None
    db.set_message_created_at(steering.id, reply.created_at + timedelta(microseconds=1))
    logger.info(
        "Unanswered steering moved after the reply",
        extra={"conversation_id": conv_id, "message_id": steering.id},
    )
    return steering.id
