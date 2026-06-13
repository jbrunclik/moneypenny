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
You produce a short morning briefing. ALWAYS call these tools before
writing, in parallel where possible:
1. The calendar tool for today's events (note the first meeting and
   any conflicts)
2. The task tool for tasks that are ACTIONABLE NOW - filter to overdue,
   today, and the next 3 days (e.g. filter "overdue | today | next 3
   days"). Never surface tasks whose due date is weeks or months away,
   even as low-effort filler - a task due next year is not for today
3. The Garmin tool for last night's sleep and recovery - call it every
   time. Read recovery from the FINALIZED wake-time values:
   `bodyBatteryAtWakeTime` (the overnight peak at wake - NOT the current
   or most-recent reading, which is still climbing if the run fired
   before you woke) and resting heart rate from the daily summary
4. The kv_store tool with namespace "sports": `list` the keys; when
   training programs exist, `get` `<program_id>:routine` and
   `<program_id>:last_session` to determine whether a training is
   planned for today and what exactly it is

Then write the briefing:
- The VERY FIRST line must be a one-line summary of the day. No
  greeting, no salutation, no preamble - this line is the notification
  preview on the user's lock screen, so it must carry information
- Follow with a compact agenda: events with times, then top tasks
- Add one line on readiness from the finalized wake-time metrics (Body
  Battery at wake, resting HR, sleep quality) and what they mean for
  training/recovery today. If those values are missing or zero, the
  briefing ran before you woke - omit the readiness section rather than
  reporting provisional mid-sleep numbers that understate recovery
- **Training**: if the routine schedules a workout today, state it
  concretely (exercises/duration/intensity from the routine), adjusted
  for today's readiness; suggest a realistic time slot around the
  calendar. Skip the section when nothing is scheduled
- Close with one concrete recommendation for how to structure the day

Keep it under 250 words, use the user's preferred language, and skip
sections that have no data instead of mentioning they are empty."""

DEFAULT_BRIEFING_TIME = "08:00"

# System-managed agent types. Each entry maps a system_type marker to
# the current stock prompt resolved at run time; future special agents
# (evening review, ...) add a constant + registry entry here.
SYSTEM_TYPE_DAILY_BRIEFING = "daily_briefing"

SYSTEM_AGENT_PROMPTS: dict[str, str] = {
    SYSTEM_TYPE_DAILY_BRIEFING: BRIEFING_SYSTEM_PROMPT,
}

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


def resolve_agent_system_prompt(agent: Agent) -> str | None:
    """Effective system prompt for an agent run.

    System-managed agents (agent.system_type set) store NULL while on
    the stock prompt; the current default is resolved from code here at
    run time - prompt improvements ship with deploys, no migration or
    user action needed. A non-null prompt is a user customization and
    always wins.
    """
    if agent.system_prompt:
        return agent.system_prompt
    if agent.system_type:
        return SYSTEM_AGENT_PROMPTS.get(agent.system_type)
    return None


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
            # NULL = stock prompt, resolved from code at run time (see
            # resolve_agent_system_prompt) so improvements ship with
            # deploys; the editor stores a value only on customization
            system_prompt=None,
            schedule=schedule,
            timezone=timezone,
            tool_permissions=None,  # all tools (calendar, todoist, garmin, ...)
            enabled=True,
            # Briefings are independent reports - never feed yesterday's
            # run back into the LLM
            fresh_context=True,
            system_type=SYSTEM_TYPE_DAILY_BRIEFING,
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
            # Enforced for the settings-managed briefing: independent
            # runs, and unrestricted tools (the briefing needs calendar/
            # tasks/Garmin; this also self-heals agents that lost their
            # tools to the old editor trap)
            fresh_context=True,
            tool_permissions=None,
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
