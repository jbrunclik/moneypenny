"""Lightweight items set from chat: reminders, check-ins, watchers, recurring checks.

Every item belongs to the chat that set it (docs/features/agents.md): a
reminder pushes at a time, a check-in asks its question back in the chat, a
watcher checks the web until its condition is met, a recurring check reports
on a schedule. Nothing is stored until the user confirmed: a create without
confirm=true returns a preview and keeps it pending for the conversation; a
confirm stores exactly that pending item, and only in a later turn (the user
replied to it) - so neither drifted fields nor a page's injected "confirm" in
the same turn can schedule something the user never saw. The model fills
structured fields; the schedule itself is built by code
(src/utils/schedule_spec.py) in the household timezone.
"""

import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import TypedDict
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from src.agent.tool_results import get_current_request_id
from src.agent.tools.context import get_conversation_context
from src.agent.tools.errors import tool_error
from src.config import Config
from src.db.models import db
from src.db.models.dataclasses import ItemKind, ScheduledItem
from src.enums import MessageRole
from src.utils.clock import utc_now
from src.utils.logging import get_logger
from src.utils.schedule_spec import (
    ScheduleError,
    describe_cron,
    describe_instant,
    describe_interval,
    next_cron_run,
    one_off_instant,
    recurring_cron,
    until_instant,
    watch_interval_hours,
)
from src.utils.threat_patterns import find_injection

logger = get_logger(__name__)

# The preview awaiting the user's answer, per conversation (kv: multi-worker safe)
_PENDING_NAMESPACE = "schedule_pending"
_NO_PUSH_NOTE = (
    " Note: none of the user's devices has notifications turned on, so this"
    " cannot reach them - tell them to turn notifications on in the app."
)
_KIND_LABELS: dict[str, str] = {
    "reminder": "reminder",
    "check_in": "check-in",
    "watcher": "watcher",
    "recurring": "recurring check",
}
_ONE_OFFS = {"reminder", "check_in"}
_SHORT_DATE = "%d %b"


class Spec(TypedDict, total=False):
    """A pending preview: what ScheduledItem needs (instants as ISO strings,
    JSON-safe for the kv store), plus the descriptions shown and the turn."""

    kind: ItemKind
    text: str
    end_condition: str
    schedule: str
    interval_hours: int
    next_run_at: str
    expires_at: str | None
    when: str
    ends: str
    turn: str
    request: str  # the chat turn that previewed it (a confirm needs a later turn)


def _until(args: Mapping[str, object], now: datetime) -> datetime | str | None:
    """The user's end date (end of that local day), None, or a tool error."""
    raw = str(args.get("until") or "").strip()
    if not raw:
        return None
    end = until_instant(raw, Config.APP_TIMEZONE, now)
    return tool_error(end.message) if isinstance(end, ScheduleError) else end


def _short(instant: datetime) -> str:
    return instant.astimezone(ZoneInfo(Config.APP_TIMEZONE)).strftime(_SHORT_DATE).lstrip("0")


def _one_off(kind: str, args: Mapping[str, object], now: datetime) -> Spec | str:
    tz = Config.APP_TIMEZONE
    instant = one_off_instant(str(args.get("date") or ""), str(args.get("time") or ""), tz, now)
    if isinstance(instant, ScheduleError):
        return tool_error(instant.message)
    return {
        "next_run_at": instant.isoformat(),
        "when": describe_instant(instant, tz),
        "ends": "then done",
    }


def _watcher(args: Mapping[str, object], now: datetime) -> Spec | str:
    condition = str(args.get("end_condition") or "").strip()
    if not condition:
        return tool_error("'end_condition' is required for a watcher: when should it stop?")
    hours = watch_interval_hours(str(args.get("interval") or "daily"))
    if isinstance(hours, ScheduleError):
        return tool_error(hours.message)
    until = _until(args, now)
    if isinstance(until, str):
        return until
    limit = f"until {_short(until)}" if until else f"{Config.SCHEDULE_WATCH_EXPIRY_DAYS} days"
    return {
        "end_condition": condition,
        "interval_hours": hours,
        "next_run_at": now.isoformat(),
        # Only a date the user gave is stored: no back-off for those (watch_expiry)
        "expires_at": until.isoformat() if until else None,
        "when": f"checks {describe_interval(hours)}",
        "ends": f"until {condition}, at most {limit}",
    }


def _recurring(args: Mapping[str, object], now: datetime) -> Spec | str:
    days = args.get("days")
    cron = recurring_cron(
        [str(d) for d in days] if isinstance(days, list) else [], str(args.get("time") or "")
    )
    if isinstance(cron, ScheduleError):
        return tool_error(cron.message)
    until = _until(args, now)
    if isinstance(until, str):
        return until
    return {
        "schedule": cron,
        "next_run_at": next_cron_run(cron, Config.APP_TIMEZONE, now).isoformat(),
        "expires_at": until.isoformat() if until else None,
        "when": describe_cron(cron),
        "ends": f"until {_short(until)}" if until else "until cancelled",
    }


def _build(kind: str, args: Mapping[str, object], now: datetime) -> Spec | str:
    if kind in _ONE_OFFS:
        return _one_off(kind, args, now)
    if kind == "watcher":
        return _watcher(args, now)
    if kind == "recurring":
        return _recurring(args, now)
    return tool_error("kind must be reminder, check_in, watcher or recurring.")


def _push_note(user_id: str) -> str:
    """Warn when an item's push has no device to reach."""
    return "" if db.get_push_subscriptions(user_id) else _NO_PUSH_NOTE


def _latest_user_message_id(conversation_id: str) -> str:
    """The turn marker: production saves each user message before the agent runs."""
    return next(
        (m.id for m in reversed(db.get_messages(conversation_id)) if m.role == MessageRole.USER),
        "",
    )


def _keep_pending(user_id: str, conversation_id: str, spec: Spec) -> None:
    """Hold the preview for the user's answer. Re-previewing the very item
    they already saw keeps its turn: it stays answered, so confirmable."""
    spec["turn"] = _latest_user_message_id(conversation_id)
    spec["request"] = get_current_request_id() or ""
    if raw := db.kv_get(user_id, _PENDING_NAMESPACE, conversation_id):
        previous: Spec = json.loads(raw)
        markers = {"turn", "request"}
        if {k: v for k, v in previous.items() if k not in markers} == {
            k: v for k, v in spec.items() if k not in markers
        }:
            spec["turn"] = previous["turn"]
            spec["request"] = previous.get("request", "")
    db.kv_set(user_id, _PENDING_NAMESPACE, conversation_id, json.dumps(spec))


def _instant(value: str | None) -> datetime | None:
    # tz-naive: values are isoformats of aware UTC instants this module built
    return datetime.fromisoformat(value) if value else None


def _confirmed_next_run(pending: Spec) -> datetime:
    """When the item first acts; a recurring check counts from the confirm (one
    confirmed after the previewed time would otherwise run at once, off-schedule)."""
    if pending["kind"] == "recurring" and pending.get("schedule"):
        return next_cron_run(pending["schedule"], Config.APP_TIMEZONE, utc_now())
    # tz-naive: an isoformat of an aware UTC instant this module built
    return datetime.fromisoformat(pending["next_run_at"])


def _new_item(user_id: str, conversation_id: str, pending: Spec) -> ScheduledItem:
    return ScheduledItem(
        id=str(uuid.uuid4()),
        user_id=user_id,
        conversation_id=conversation_id,
        kind=pending["kind"],
        text=pending["text"],
        end_condition=pending.get("end_condition"),
        schedule=pending.get("schedule"),
        interval_hours=pending.get("interval_hours"),
        next_run_at=_confirmed_next_run(pending),
        expires_at=_instant(pending.get("expires_at")),
        status="active",
        last_result=None,
        quiet_runs=0,
        failures=0,
        created_at=utc_now(),
    )


def _confirm_refusal(user_id: str, conversation_id: str, pending: Spec) -> str | None:
    request = get_current_request_id()
    same_turn = bool(request) and request == pending.get("request")
    # A newer user message in the same turn is an interjection, not an answer
    if same_turn or pending["turn"] == _latest_user_message_id(conversation_id):
        return tool_error(
            "The user has not answered the preview yet - show it and ask them; confirm "
            "only after they agree in their reply."
        )
    tz = Config.APP_TIMEZONE
    due = _instant(pending["next_run_at"])
    if pending["kind"] in _ONE_OFFS and due is not None and due <= utc_now():
        return tool_error(
            f"That time has passed - it is now {describe_instant(utc_now(), tz)} ({tz}). "
            "Preview a new time."
        )
    cap = Config.SCHEDULE_MAX_ACTIVE_PER_USER
    if (count := db.count_items(user_id)) >= cap:
        return tool_error(
            f"You already have {count} scheduled items (limit {cap}); delete one first."
        )
    return None


def _confirm(user_id: str, conversation_id: str) -> str:
    """Store the conversation's pending preview, once the user has answered it."""
    raw = db.kv_get(user_id, _PENDING_NAMESPACE, conversation_id)
    if not raw:
        return tool_error(
            "Nothing was previewed in this chat to confirm: call create without confirm "
            "first, show the preview and ask the user."
        )
    pending: Spec = json.loads(raw)
    if refusal := _confirm_refusal(user_id, conversation_id, pending):
        return refusal
    db.kv_delete(user_id, _PENDING_NAMESPACE, conversation_id)
    item = db.add_item(_new_item(user_id, conversation_id, pending))
    logger.info(
        "Scheduled item created from chat",
        extra={"user_id": user_id, "item_id": item.id, "kind": item.kind},
    )
    label = _KIND_LABELS[item.kind]
    return (
        f"Scheduled {label} id={item.id} - {pending['when']} ({Config.APP_TIMEZONE}), "
        f'{pending["ends"]}: "{item.text}".' + _push_note(user_id)
    )


def _create(user_id: str, conversation_id: str | None, args: Mapping[str, object]) -> str:
    if not conversation_id:
        return tool_error("Scheduling needs a chat to belong to.", retriable=False)
    if args.get("confirm"):
        return _confirm(user_id, conversation_id)
    text = str(args.get("text") or "").strip()
    if not text:
        return tool_error("'text' is required: the reminder, the question, or what to check.")
    # Every free-text field that reaches a future run is screened, not just text
    for value in (text, str(args.get("end_condition") or "")):
        if reason := find_injection(value):
            return tool_error(f"Refused: {reason}. Describe it in your own words.")
    kind = str(args.get("kind") or "")
    spec = _build(kind, args, utc_now())
    if isinstance(spec, str):
        return spec
    spec["kind"], spec["text"] = kind, text  # type: ignore[typeddict-item]  # kind checked by _build
    _keep_pending(user_id, conversation_id, spec)
    return (
        f"PREVIEW: {_KIND_LABELS[kind]} - {spec['when']} ({Config.APP_TIMEZONE}), "
        f'{spec["ends"]}: "{text}". Nothing is scheduled yet: show this to the user and ask; '
        "when they agree in their reply, call create with confirm=true." + _push_note(user_id)
    )


def describe_when(item: ScheduledItem) -> str:
    """When the item next acts, for lists and previews."""
    if item.kind == "watcher" and item.interval_hours:
        return f"checks {describe_interval(item.interval_hours)}"
    if item.kind == "recurring" and item.schedule:
        try:
            return describe_cron(item.schedule)
        except ValueError:  # a standing job's cron, beyond what the tool builds
            return f"on the schedule `{item.schedule}`"
    return describe_instant(item.next_run_at, Config.APP_TIMEZONE)


def watch_expiry(item: ScheduledItem) -> datetime | None:
    """When the item stops on its own: the user's end date, or for a watcher
    without one, SCHEDULE_WATCH_EXPIRY_DAYS after it was set."""
    if item.expires_at is not None or item.kind != "watcher":
        return item.expires_at
    return item.created_at + timedelta(days=Config.SCHEDULE_WATCH_EXPIRY_DAYS)


def describe_ends(item: ScheduledItem) -> str:
    """How the item ends, for lists and previews."""
    if item.kind in _ONE_OFFS:
        return "then done"
    if item.kind == "watcher":
        expiry = watch_expiry(item)
        limit = f", at most until {_short(expiry)}" if expiry else ""
        return f"until {item.end_condition}{limit}"
    return f"until {_short(item.expires_at)}" if item.expires_at else "until cancelled"


def _list(user_id: str) -> str:
    items = db.list_items(user_id)
    if not items:
        return "Nothing is scheduled from chat."
    lines = [
        f"- {_KIND_LABELS[i.kind]} id={i.id} ({i.status}): {describe_when(i)}, "
        f'{describe_ends(i)} - "{i.text}"'
        for i in items
    ]
    return f"Scheduled from chat ({Config.APP_TIMEZONE}):\n" + "\n".join(lines)


def _manage(action: str, user_id: str, item_id: str) -> str:
    item = db.get_item(item_id, user_id)
    if item is None:
        return tool_error(f"No scheduled item with id={item_id} - call schedule(action='list').")
    if db.is_agent_job(item.id):
        return tool_error(
            "That is an agent's schedule: the user manages it from Agents, not here.",
            retriable=False,
        )
    label: ItemKind = item.kind
    if action == "delete":
        db.delete_item(item.id, user_id)
        return f'Deleted {_KIND_LABELS[label]} "{item.text}".'
    if item.kind in _ONE_OFFS:
        return tool_error(f"A {_KIND_LABELS[label]} cannot be paused: delete it instead.")
    if not db.set_item_paused(item.id, user_id, paused=action == "pause"):
        return tool_error(
            f"The {_KIND_LABELS[label]} is running right now (or already {action}d) - try again in a minute."
        )
    return f'{"Paused" if action == "pause" else "Resumed"} {_KIND_LABELS[label]} "{item.text}".'


@tool
def schedule(
    action: str,
    kind: str | None = None,
    text: str | None = None,
    date: str | None = None,
    time: str | None = None,
    days: list[str] | None = None,
    until: str | None = None,
    interval: str | None = None,
    end_condition: str | None = None,
    item_id: str | None = None,
    confirm: bool = False,
) -> str:
    """Set reminders, check-ins, watchers and recurring checks for the user, and manage them.

    Everything belongs to this chat: results arrive here as a new message
    (and a push), and deleting the chat deletes them. Times are local.

    create: first call WITHOUT confirm - it returns a preview and stores
    nothing. Show the preview to the user and ask; only after they agree in
    their reply, call create with confirm=true (no other fields needed): it
    stores exactly the item previewed in this chat.
      - kind="reminder": a one-off push. text = what to remind about,
        date + time.
      - kind="check_in": at date + time, ask the user a question back in
        this chat ("check with me Friday how it's healing"). text = the
        question to ask then, written now from this conversation.
      - kind="watcher": check a public web page until something happens,
        then report and stop ("tell me when the school posts a teacher job").
        text = what to check (with its URL if known), end_condition = when
        to stop, interval = 6h, daily or weekly (how urgent), optional
        until = last day. Only public pages - not email, mail or accounts.
      - kind="recurring": a regular check you run and report on. text = the
        task, days = mon..sun or ["daily"] / ["weekdays"] / ["weekends"],
        time, optional until.
    list: everything scheduled from chat, with ids.
    pause / resume (watchers, recurring) and delete (any): item_id from list.

    Args:
        action: create, list, pause, resume or delete.
        kind: reminder, check_in, watcher or recurring (create).
        text: The reminder, the check-in question, or what to check or do.
        date: YYYY-MM-DD (reminder, check_in).
        time: HH:MM, 24-hour, local time (reminder, check_in, recurring).
        days: Days for recurring: mon..sun, or daily, weekdays, weekends.
        until: YYYY-MM-DD, the last day (watcher, recurring; optional).
        interval: 6h, daily or weekly (watcher).
        end_condition: When a watcher stops (watcher).
        item_id: The id from list (pause, resume, delete).
        confirm: true only after the user agreed to the preview in their reply.
    """
    conversation_id, user_id = get_conversation_context()
    if not user_id:
        return tool_error("No user context available.", retriable=False)
    from src.agent.executor import get_agent_context  # noqa: PLC0415 - cycle: executor imports the tools

    if get_agent_context() is not None:
        return tool_error("A scheduled run cannot create or change schedules.", retriable=False)
    if action == "create":
        args = {
            "kind": kind,
            "text": text,
            "date": date,
            "time": time,
            "days": days,
            "until": until,
            "interval": interval,
            "end_condition": end_condition,
            "confirm": confirm,
        }
        return _create(user_id, conversation_id, args)
    if action == "list":
        return _list(user_id)
    if action in {"pause", "resume", "delete"}:
        if not item_id:
            return tool_error(
                f"'item_id' is required for {action} - call schedule(action='list') first."
            )
        return _manage(action, user_id, item_id)
    return tool_error("action must be create, list, pause, resume or delete.")
