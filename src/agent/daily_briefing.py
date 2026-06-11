"""Settings-managed Daily Briefing agent.

The Daily Briefing is an ordinary autonomous agent - it reuses the
scheduler, executor, dedicated conversation, push-on-completion, and
Command Center observability. This module owns the Settings-facing
lifecycle: deriving {enabled, time, timezone} from the agent record and
upserting the agent when the user changes the toggle or delivery time.

The user record points at the agent via users.daily_briefing_agent_id.
If the user deletes the agent from Command Center the pointer dangles;
status reports disabled and the next enable creates a fresh agent.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.db.models import Agent, Database, User

logger = get_logger(__name__)


def _db() -> Database:
    """Resolve the database at call time so test patches of
    src.db.models.db are honored."""
    from src.db.models import db

    return db


BRIEFING_AGENT_NAME = "Daily Briefing"

BRIEFING_AGENT_DESCRIPTION = "Morning summary of your day (managed from Settings)"

BRIEFING_SYSTEM_PROMPT = """\
You produce a short morning briefing. Use your tools to gather:
- Today's calendar events (note the first meeting and any conflicts)
- Open tasks, highlighting priorities and anything overdue
- Garmin readiness/sleep data when available

Then write the briefing:
- Start with a one-line summary of the day (this becomes the
  notification preview, so make it count)
- Follow with a compact agenda: events with times, then top tasks
- If readiness/sleep data is available, add one line of training or
  recovery advice
- Close with one concrete recommendation for how to structure the day

Keep it under 200 words, use the user's preferred language, and skip
sections that have no data instead of mentioning they are empty."""

DEFAULT_BRIEFING_TIME = "08:00"

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _time_to_cron(time_str: str) -> str:
    """'07:30' -> '30 7 * * *'."""
    match = _TIME_RE.match(time_str)
    if not match:
        raise ValueError(f"Invalid briefing time: {time_str!r}")
    hour, minute = int(match.group(1)), int(match.group(2))
    return f"{minute} {hour} * * *"


def _cron_to_time(cron: str | None) -> str | None:
    """'30 7 * * *' -> '07:30'; None for non-daily/missing schedules."""
    if not cron:
        return None
    parts = cron.split()
    if len(parts) != 5 or parts[2:] != ["*", "*", "*"]:
        return None
    try:
        minute, hour = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def _resolve_agent(user: User) -> Agent | None:
    if not user.daily_briefing_agent_id:
        return None
    return _db().get_agent(user.daily_briefing_agent_id, user.id)


def get_briefing_status(user: User) -> dict[str, object]:
    """Settings view of the briefing: {enabled, time, timezone}."""
    agent = _resolve_agent(user)
    if not agent:
        return {"enabled": False, "time": DEFAULT_BRIEFING_TIME, "timezone": "UTC"}
    return {
        "enabled": agent.enabled and bool(agent.schedule),
        "time": _cron_to_time(agent.schedule) or DEFAULT_BRIEFING_TIME,
        "timezone": agent.timezone,
    }


def set_briefing(user: User, enabled: bool, time_str: str, timezone: str) -> dict[str, object]:
    """Create or update the briefing agent to match the Settings values.

    Returns the resulting status dict (same shape as get_briefing_status).
    """
    schedule = _time_to_cron(time_str)
    agent = _resolve_agent(user)

    if agent is None:
        if not enabled:
            # Nothing to do - don't create a disabled agent
            return {"enabled": False, "time": time_str, "timezone": timezone}
        agent = _db().create_agent(
            user_id=user.id,
            name=BRIEFING_AGENT_NAME,
            description=BRIEFING_AGENT_DESCRIPTION,
            system_prompt=BRIEFING_SYSTEM_PROMPT,
            schedule=schedule,
            timezone=timezone,
            tool_permissions=None,  # all tools (calendar, todoist, garmin, ...)
            enabled=True,
        )
        _db().update_user_daily_briefing_agent(user.id, agent.id)
        logger.info(
            "Daily briefing agent created",
            extra={"user_id": user.id, "agent_id": agent.id, "time": time_str},
        )
    else:
        _db().update_agent(
            agent.id,
            user.id,
            schedule=schedule,
            timezone=timezone,
            enabled=enabled,
        )
        logger.info(
            "Daily briefing agent updated",
            extra={
                "user_id": user.id,
                "agent_id": agent.id,
                "enabled": enabled,
                "time": time_str,
            },
        )

    return {"enabled": enabled, "time": time_str, "timezone": timezone}
