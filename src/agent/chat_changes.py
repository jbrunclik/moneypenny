"""Destructive changes asked for in chat wait on a card (one approval mechanism, step 4).

In a chat turn, a call in the run gate's list (permission_check.
DESTRUCTIVE_OPERATIONS: Todoist deletes and archives, Calendar delete_event,
the Rouvy delete) does not run: hold_destructive_call puts it on the turn's
one chat_change card - its tool, full arguments and the item's name, looked
up from the integration - and the tool returns the card text instead. All of
a turn's destructive calls share that card (one row each) and apply together:
approving runs each stored call through its tool (the hold is bypassed), as
the user who asked, and the result line says what was done
(docs/features/proposals.md).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from src.agent.proposals import (
    ProposalFailedError,
    card_shown,
    file_proposal,
    register_kind,
)
from src.agent.tool_results import get_current_request_id
from src.agent.tools.context import get_conversation_context, set_conversation_context
from src.db.models import db
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from src.db.models import Proposal, ProposalOption

logger = get_logger(__name__)

KIND = "chat_change"
_ERROR_MAX_CHARS = 120
_SUMMARY_ITEM_CHARS = 60

# (verb, noun) per gated operation, as the card says it
_WORDS: dict[tuple[str, str], tuple[str, str]] = {
    ("todoist", "delete_task"): ("Delete", "task"),
    ("todoist", "delete_project"): ("Delete", "project"),
    ("todoist", "delete_section"): ("Delete", "section"),
    ("todoist", "archive_project"): ("Archive", "project"),
    ("google_calendar", "delete_event"): ("Delete", "event"),
    ("rouvy_workout", "delete"): ("Delete", "Rouvy workout"),
}

# The stored calls are being performed: the gate lets them through
_applying: ContextVar[bool] = ContextVar("chat_change_applying", default=False)
# A round's calls run in parallel threads: one card per turn, not one each
_card_lock = threading.Lock()


def _operation(args: Mapping[str, object]) -> str:
    return str(args.get("operation") or args.get("action") or "")


def _item_id(args: Mapping[str, object]) -> str:
    for key in ("task_id", "project_id", "section_id", "event_id", "workout_id"):
        if args.get(key):
            return str(args[key])
    return ""


def _lookups() -> dict[str, Callable[[Mapping[str, object]], str | None]]:
    """Each integration names its item (looked up at the call)."""
    from src.agent.tools.google_calendar import event_label  # noqa: PLC0415 - cycle: the tools import the gate
    from src.agent.tools.rouvy import workout_name  # noqa: PLC0415 - cycle: the tools import the gate
    from src.agent.tools.todoist import item_name  # noqa: PLC0415 - cycle: the tools import the gate

    return {"todoist": item_name, "google_calendar": event_label, "rouvy_workout": workout_name}


def item_label(tool: str, args: Mapping[str, object]) -> str:
    """The item a call changes, by name; its id when the lookup fails."""
    lookup = _lookups().get(tool)
    try:
        name = lookup(args) if lookup else None
    except Exception:  # a lookup never blocks the card
        logger.warning("Chat change lookup failed", extra={"tool": tool}, exc_info=True)
        name = None
    return name or _item_id(args)


def _call_words(call: Mapping[str, object]) -> tuple[str, str]:
    args = call.get("args")
    operation = _operation(args) if isinstance(args, Mapping) else ""
    return _WORDS.get((str(call.get("tool")), operation), ("Change", "item"))


def _short(item: str) -> str:
    """An item name cut for the card's summary (its row keeps it whole)."""
    return item if len(item) <= _SUMMARY_ITEM_CHARS else item[: _SUMMARY_ITEM_CHARS - 1] + "…"


def _card(calls: list[dict[str, object]]) -> tuple[str, dict[str, object], list[ProposalOption]]:
    """Summary, one row per call, and the one option."""
    words = [_call_words(c) for c in calls]
    verbs = {verb for verb, _ in words}
    verb = verbs.pop() if len(verbs) == 1 else None
    if len(calls) == 1:
        summary = f"{words[0][0]} {words[0][1]} “{_short(str(calls[0]['item']))}”"
    else:
        summary = f"{verb or 'Change'} {len(calls)} items"
    rows: dict[str, object] = {}
    for (row_verb, noun), call in zip(words, calls, strict=True):
        label = f"{row_verb} {noun}"
        repeat = sum(1 for key in rows if key == label or key.startswith(f"{label} ("))
        rows[f"{label} ({repeat + 1})" if repeat else label] = call["item"]
    option: ProposalOption = {
        "label": verb or "Do it",
        "description": "",
        "payload": {"calls": calls},
    }
    return summary, rows, [option]


def hold_destructive_call(tool: str, args: Mapping[str, object]) -> str | None:
    """A chat turn's delete or archive: put it on the turn's card and return
    the card text for the tool's result; None lets the call run."""
    from src.agent.tools.permission_check import DESTRUCTIVE_OPERATIONS  # noqa: PLC0415 - cycle: permission_check imports this module

    if _applying.get() or _operation(args) not in DESTRUCTIVE_OPERATIONS.get(tool, frozenset()):
        return None
    if not _item_id(args):
        return None  # the tool's own "needs task_id" error goes back to the model
    request_id = get_current_request_id()
    conversation_id, _user_id = get_conversation_context()
    if not (request_id and conversation_id):
        return None  # no turn to show a card in (a script)
    call: dict[str, object] = {"tool": tool, "args": dict(args), "item": item_label(tool, args)}
    with _card_lock:
        existing = db.turn_proposal(request_id, KIND)
        held = _calls(existing) if existing else []
        if existing and any(_same(c, call) for c in held):
            return card_shown(existing)  # the same call again: already on the card
        calls = [*held, call]
        summary, rows, options = _card(calls)
        if existing:
            db.extend_proposal(existing.id, summary, rows, options)
            card = db.get_proposal(existing.id, existing.user_id) or existing
        else:
            card = file_proposal(KIND, summary, rows, options)
    logger.info("Chat change held", extra={"tool": tool, "calls": len(calls)})
    return card_shown(card)


def _same(held: Mapping[str, object], call: Mapping[str, object]) -> bool:
    return held.get("tool") == call.get("tool") and held.get("args") == call.get("args")


def _calls(proposal: Proposal) -> list[dict[str, object]]:
    calls = proposal.options[0]["payload"].get("calls")
    return [dict(c) for c in calls] if isinstance(calls, list) else []


@contextmanager
def _as_the_user(proposal: Proposal) -> Iterator[None]:
    """Perform the calls in the card's conversation, past the hold."""
    previous = get_conversation_context()
    token = _applying.set(True)
    set_conversation_context(proposal.conversation_id, proposal.user_id)
    try:
        yield
    finally:
        set_conversation_context(*previous)
        _applying.reset(token)


def _tools() -> dict[str, BaseTool]:
    from src.agent.tools.google_calendar import google_calendar  # noqa: PLC0415 - cycle: the tools import the gate
    from src.agent.tools.rouvy import rouvy_workout  # noqa: PLC0415 - cycle: the tools import the gate
    from src.agent.tools.todoist import todoist  # noqa: PLC0415 - cycle: the tools import the gate

    return {"todoist": todoist, "google_calendar": google_calendar, "rouvy_workout": rouvy_workout}


def _failure(result: object) -> str | None:
    """Why a tool result is a failure, or None when it succeeded."""
    try:
        parsed = json.loads(str(result))
    except ValueError:
        return None
    if isinstance(parsed, dict) and (parsed.get("error") or parsed.get("success") is False):
        return str(parsed.get("error") or parsed.get("message") or "failed")[:_ERROR_MAX_CHARS]
    return None


def _perform(call: Mapping[str, object]) -> str | None:
    """Run one stored call; why it failed, or None."""
    tool = _tools().get(str(call.get("tool")))
    if tool is None:
        return "unknown tool"
    try:
        args = call.get("args")
        return _failure(tool.invoke(dict(args) if isinstance(args, Mapping) else {}))
    except Exception as e:  # one failing call must not stop the others
        logger.warning("Chat change call failed", extra={"tool": call.get("tool")}, exc_info=True)
        return str(e)[:_ERROR_MAX_CHARS]


def apply_chat_change(proposal: Proposal, option: ProposalOption) -> str:
    """Approved: perform every call on the card, exactly as stored."""
    calls = _calls(proposal)
    started = time.monotonic()
    done: list[str] = []
    failed: list[str] = []
    with _as_the_user(proposal):
        for call in calls:
            _verb, noun = _call_words(call)
            what = f"{noun} “{call['item']}”"
            error = _perform(call)
            (failed if error else done).append(f"{what} ({error})" if error else what)
    logger.info(
        "Chat change applied",
        extra={
            "calls": len(calls),
            "failed": len(failed),
            "ms": round((time.monotonic() - started) * 1000),
        },
    )
    if not done:
        raise ProposalFailedError("; ".join(failed))
    if failed:
        return f"Done {len(done)} of {len(calls)} - not done: {'; '.join(failed)}."
    return f"Done - {', '.join(done)}."


# A delete's own verb is a yes to its card ("smaž to"), so a natural reply
# does not expire it into a confirm loop
_VERB_YES = frozenset(
    {
        "delete", "delete it", "delete them", "yes delete", "yes delete it",
        "archive", "archive it", "yes archive",
        "smaž", "smaž to", "smaž je", "smazat", "ano smaž", "ano smazat", "jo smaž",
        "archivuj", "archivovat", "ano archivuj",
    }
)  # fmt: skip

register_kind(KIND, apply_chat_change, extra_yes=_VERB_YES)
