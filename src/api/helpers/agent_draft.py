"""A chat's watcher or recurring check, drafted as a full agent.

Command Center's "Make an agent" opens the agent editor with this draft; the
create that names the item (replaces_item_id) removes it, so the agent takes
over the job (docs/features/agents.md).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.agent.item_runner import RUN_TOOL_NAMES
from src.config import Config
from src.constants import AGENT_NAME_MAX_CHARS
from src.db.models.dataclasses import ScheduledItem

PROMOTABLE_KINDS = frozenset({"watcher", "recurring"})
# The tools these jobs run with, in the editor's order
_GRANTS = [name for name in ("web_search", "fetch_url", "research") if name in RUN_TOOL_NAMES]
_NAME_CHARS = min(AGENT_NAME_MAX_CHARS, 60)
_HOURS_PER_DAY = 24
_HOURS_PER_WEEK = 168


def _cron_for_watcher(interval_hours: int, next_run: datetime, timezone: str) -> str:
    """A watcher's interval as a cron, at its next check's local time."""
    at = next_run.astimezone(ZoneInfo(timezone))
    if interval_hours < _HOURS_PER_DAY and _HOURS_PER_DAY % interval_hours == 0:
        return f"{at.minute} */{interval_hours} * * *"
    if interval_hours >= _HOURS_PER_WEEK:
        return f"{at.minute} {at.hour} * * {at.isoweekday() % 7}"
    return f"{at.minute} {at.hour} * * *"


def _instructions(item: ScheduledItem) -> str:
    parts = [item.text.strip()]
    if item.kind == "watcher":
        if item.end_condition:
            parts.append(f"Stop when: {item.end_condition.strip()}")
        parts.append("Report only what changed since your last report.")
    parts.append("When there is nothing worth telling, reply [SILENT].")
    return "\n\n".join(parts)


def _name(text: str) -> str:
    first_line = text.strip().splitlines()[0] if text.strip() else "Agent"
    if len(first_line) <= _NAME_CHARS:
        return first_line
    return first_line[: _NAME_CHARS - 1].rstrip() + "…"


def agent_draft(item: ScheduledItem) -> dict[str, object]:
    """The agent editor's starting point for a promotable item."""
    timezone = item.timezone or Config.APP_TIMEZONE
    if item.kind == "recurring":
        schedule = item.schedule
    else:
        schedule = _cron_for_watcher(
            item.interval_hours or _HOURS_PER_DAY, item.next_run_at, timezone
        )
    return {
        "name": _name(item.text),
        "instructions": _instructions(item),
        "schedule": schedule,
        "timezone": timezone,
        "grants": list(_GRANTS),
        # A watcher compares with its last report: the agent keeps its history
        "fresh_context": False,
        "replaces_item_id": item.id,
    }
