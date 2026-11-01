"""What a lost turn already did, told to the conversation's next turn.

Oct 2026: a deploy gives running turns gunicorn's graceful timeout while tool
turns run p90 ~42 s, so a turn can die right after a Todoist or Calendar
write; a model failure after a write and before any text ends the same way.
Its empty reply is deleted and Retry answers the question again from scratch -
with no record of the write, which could then happen twice.

Before such a reply is deleted, its stream journal (tool_start/tool_end
events, kept STREAM_JOURNAL_TTL_SECONDS) is read for side-effecting tool
calls, and kv_store carries them to the conversation's next turn: the retry
may land on another worker. A batch turn journals nothing, so it leaves no
record.
"""

import json
import re
from collections import Counter

from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)

KV_NAMESPACE = "lost_actions"

# Tools whose calls change something outside the reply. Reads (search, Garmin
# stats, places) are safe to repeat and stay out of the note
SIDE_EFFECT_TOOLS = frozenset(
    {
        "todoist",
        "google_calendar",
        "whatsapp",
        "manage_memory",
        "kv_store",
        "garmin_workout",
        "rouvy_workout",
        "save_place",
        "delete_place",
        "create_artifact",
        "update_artifact",
        "trigger_agent",
        "browser",
    }
)

_NOTE = (
    "Your previous attempt at this turn was cut off (a server restart or an "
    "error) after it had already run these actions:\n{actions}\n"
    "Do not repeat them blindly: check the current state first (e.g. list the "
    "tasks or events) and run only what is still missing. Tell the user what "
    "had already been done."
)


# A detail is the model's own tool arguments - possibly text copied from a
# page - and the note is promoted to guidance: no markers, a short line
_MARKER = re.compile(r"\[/?\s*SYSTEM GUIDANCE\s*\]", re.IGNORECASE)
_DETAIL_MAX_CHARS = 120


def _clean(detail: str) -> str:
    detail = " ".join(_MARKER.sub("", detail).split())
    return detail if len(detail) <= _DETAIL_MAX_CHARS else detail[: _DETAIL_MAX_CHARS - 1] + "…"


def _journal_actions(message_id: str) -> list[str]:
    """The side-effecting tool calls in a turn's journal, in order."""
    starts: list[tuple[str, str]] = []
    ended: Counter[str] = Counter()
    for _seq, raw in db.journal_get_events(message_id, 0):
        event = json.loads(raw)
        tool = event.get("tool")
        if tool not in SIDE_EFFECT_TOOLS:
            continue
        if event.get("type") == "tool_start":
            starts.append((tool, _clean(event.get("detail") or "")))
        elif event.get("type") == "tool_end":
            ended[tool] += 1
    actions = []
    for tool, detail in starts:
        # tool_end carries no call id: calls of one tool end in order
        done = ended[tool] > 0
        ended[tool] -= 1
        status = "finished" if done else "cut off mid-call - may or may not have happened"
        actions.append(f"- {tool}: {detail} ({status})" if detail else f"- {tool} ({status})")
    return actions


def record_lost_actions(user_id: str, conv_id: str, message_id: str) -> None:
    """Keep what a turn whose reply is being discarded already did. Best-effort."""
    try:
        actions = _journal_actions(message_id)
        if not actions:
            return
        # By reply id: two cleanup paths may discard the same reply
        previous = db.kv_get(user_id, KV_NAMESPACE, conv_id)
        kept: dict[str, list[str]] = json.loads(previous) if previous else {}
        kept[message_id] = actions
        db.kv_set(user_id, KV_NAMESPACE, conv_id, json.dumps(kept))
        logger.info(
            "Lost turn actions recorded",
            extra={"conversation_id": conv_id, "message_id": message_id, "count": len(actions)},
        )
    except Exception:
        logger.warning("Recording lost turn actions failed", exc_info=True)


def pop_lost_actions_note(user_id: str, conv_id: str) -> str | None:
    """The note for the conversation's next turn, once. Best-effort."""
    try:
        stored = db.kv_get(user_id, KV_NAMESPACE, conv_id)
        if not stored:
            return None
        db.kv_delete(user_id, KV_NAMESPACE, conv_id)
        kept: dict[str, list[str]] = json.loads(stored)
        return _NOTE.format(actions="\n".join(a for actions in kept.values() for a in actions))
    except Exception:
        logger.warning("Reading lost turn actions failed", exc_info=True)
        return None
