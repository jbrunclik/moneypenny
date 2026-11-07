"""Reminders and recurring tasks set from chat ("remind me Friday at 8...").

A one-off reminder is a row the every-minute scheduler pushes (no model call);
a recurring task is an ordinary agent with only the always-safe read-only
tools. Nothing is stored until the user confirmed: a create without
confirm=true returns a preview. The model fills structured fields; the
schedule itself is built by code (src/utils/schedule_spec.py) in the
household timezone.
"""

from collections.abc import Mapping
from datetime import datetime

from langchain_core.tools import tool

from src.agent.tools.context import get_conversation_context
from src.agent.tools.errors import tool_error
from src.config import Config
from src.db.models import Agent, db
from src.utils.clock import utc_now
from src.utils.logging import get_logger
from src.utils.schedule_spec import (
    ScheduleError,
    describe_cron,
    describe_instant,
    one_off_instant,
    recurring_cron,
)
from src.utils.threat_patterns import find_injection

logger = get_logger(__name__)

# Marks the agents this tool created, so list/pause/delete see only those
CHAT_TASK_PREFIX = "Created from chat"
_NAME_MAX_CHARS = 40


def _chat_tasks(user_id: str) -> list[Agent]:
    agents = (row["agent"] for row in db.list_agents_with_status(user_id))
    return [a for a in agents if (a.description or "").startswith(CHAT_TASK_PREFIX)]


def _active_count(user_id: str) -> int:
    return len(db.list_reminders(user_id)) + sum(1 for a in _chat_tasks(user_id) if a.enabled)


def _when(
    kind: str | None, date: str | None, time: str | None, days: list[str] | None
) -> tuple[str, str] | str:
    """(schedule value, human description) or a tool error."""
    tz = Config.APP_TIMEZONE
    if kind == "reminder":
        instant = one_off_instant(date or "", time or "", tz, utc_now())
        if isinstance(instant, ScheduleError):
            return tool_error(instant.message)
        return instant.isoformat(), describe_instant(instant, tz)
    if kind == "task":
        cron = recurring_cron(days or [], time or "")
        if isinstance(cron, ScheduleError):
            return tool_error(cron.message)
        return cron, describe_cron(cron)
    return tool_error("kind must be 'reminder' (once) or 'task' (recurring).")


def _task_name(user_id: str, text: str) -> str:
    base = text if len(text) <= _NAME_MAX_CHARS else text[: _NAME_MAX_CHARS - 1].rstrip() + "…"
    name, n = base, 1
    while db.get_agent_by_name(user_id, name) is not None:
        n += 1
        name = f"{base} ({n})"
    return name


def _store(
    user_id: str, conversation_id: str | None, kind: str, text: str, value: str, when: str
) -> str:
    tz = Config.APP_TIMEZONE
    if kind == "reminder":
        # tz-naive: value is the isoformat of the aware UTC instant one_off_instant built
        reminder = db.add_reminder(user_id, conversation_id, text, datetime.fromisoformat(value))
        logger.info(
            "Reminder scheduled from chat", extra={"user_id": user_id, "reminder_id": reminder.id}
        )
        return f'Scheduled reminder id={reminder.id} for {when} ({tz}): "{text}". It arrives as a push notification.'
    agent = db.create_agent(
        user_id,
        _task_name(user_id, text),
        description=f"{CHAT_TASK_PREFIX}: {text[:200]}",
        system_prompt=text,
        schedule=value,
        timezone=tz,
        tool_permissions=[],  # the always-safe read-only tools only
    )
    logger.info(
        "Recurring task created from chat", extra={"user_id": user_id, "agent_id": agent.id}
    )
    return (
        f'Created recurring task id={agent.id} "{agent.name}" - {when} ({tz}). It runs with read-only '
        "web tools; results arrive as a push and in the Command Center."
    )


def _create(user_id: str, conversation_id: str | None, args: Mapping[str, object]) -> str:
    text = str(args.get("text") or "").strip()
    if not text:
        return tool_error("'text' is required: what to remind about, or the task to run.")
    if reason := find_injection(text):
        return tool_error(f"Refused: {reason}. Describe the reminder or task in your own words.")
    kind = args.get("kind")
    days = args.get("days")
    when = _when(
        str(kind) if kind else None,
        str(args.get("date") or ""),
        str(args.get("time") or ""),
        [str(d) for d in days] if isinstance(days, list) else None,
    )
    if isinstance(when, str):
        return when
    value, described = when
    if not args.get("confirm"):
        return (
            f'PREVIEW: {described} ({Config.APP_TIMEZONE}) - "{text}". Nothing is scheduled yet: ask the '
            "user to confirm, then call again with the same fields and confirm=true."
        )
    cap = Config.SCHEDULE_MAX_ACTIVE_PER_USER
    if (active := _active_count(user_id)) >= cap:
        return tool_error(
            f"You already have {active} active schedules (limit {cap}); delete one first."
        )
    return _store(user_id, conversation_id, str(kind), text, value, described)


def _list(user_id: str) -> str:
    tz = Config.APP_TIMEZONE
    lines = [
        f'- reminder id={r.id}: {describe_instant(r.due_at, tz)} - "{r.text}"'
        for r in db.list_reminders(user_id)
    ]
    lines += [
        f'- task id={a.id} ({"active" if a.enabled else "paused"}): {describe_cron(a.schedule or "")} - "{a.name}"'
        for a in _chat_tasks(user_id)
        if a.schedule
    ]
    if not lines:
        return "No reminders or recurring tasks set from chat."
    return f"Reminders and recurring tasks ({tz}):\n" + "\n".join(lines)


def _manage(action: str, user_id: str, item_id: str) -> str:
    if action == "delete" and db.cancel_reminder(item_id, user_id):
        return f"Deleted reminder id={item_id}."
    agent = next((a for a in _chat_tasks(user_id) if a.id == item_id), None)
    if agent is None:
        if action in {"pause", "resume"} and any(
            r.id == item_id for r in db.list_reminders(user_id)
        ):
            return tool_error("A reminder cannot be paused: delete it and create it again later.")
        return tool_error(
            f"No reminder or chat-created task with id={item_id} - call schedule(action='list')."
        )
    if action == "delete":
        db.delete_agent(agent.id, user_id)
        return f'Deleted recurring task "{agent.name}".'
    db.update_agent(agent.id, user_id, enabled=action == "resume")
    return f'{"Resumed" if action == "resume" else "Paused"} recurring task "{agent.name}".'


@tool
def schedule(
    action: str,
    kind: str | None = None,
    text: str | None = None,
    date: str | None = None,
    time: str | None = None,
    days: list[str] | None = None,
    item_id: str | None = None,
    confirm: bool = False,
) -> str:
    """Set reminders and recurring tasks for the user, and manage them.

    Use for "remind me ...", "every Monday check ...", "what reminders do I
    have?", "cancel/pause ...". Times are in the household's local time.

    create: first call WITHOUT confirm - it returns a preview and stores
    nothing. Show the preview to the user and ask; only after they agree,
    call again with the same fields and confirm=true.
      - kind="reminder": a one-off push. text = what to remind about,
        date = YYYY-MM-DD, time = HH:MM.
      - kind="task": a recurring check you will run and report on. text =
        the task in your own words (what to check and what to tell the user;
        reply exactly [SILENT] when there is nothing new), days = list of
        mon..sun or ["daily"] / ["weekdays"] / ["weekends"], time = HH:MM.
    list: the reminders and chat-created tasks, with their ids.
    pause / resume (tasks) and delete (reminders or tasks): item_id from list.

    Args:
        action: create, list, pause, resume or delete.
        kind: reminder or task (create).
        text: The reminder text, or the task to run (create).
        date: YYYY-MM-DD (reminder).
        time: HH:MM, 24-hour, local time (create).
        days: Days for a task: mon..sun, or daily, weekdays, weekends.
        item_id: The id from list (pause, resume, delete).
        confirm: true only after the user agreed to the preview.
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
