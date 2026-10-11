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
from src.api.schemas.common import MessageRole
from src.api.utils import is_empty_placeholder, streaming_message_id
from src.config import Config
from src.db.models import Message, db
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
