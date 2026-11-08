"""Settings-managed Daily Briefing agent.

The Daily Briefing is an ordinary autonomous agent - it reuses the
scheduler, executor, dedicated conversation, push-on-completion, and
Command Center observability. This module owns the Settings-facing
lifecycle: deriving {enabled, time, timezone} from the agent record and
upserting the agent when the user changes the toggle or delivery time.

The user record points at its standing job via users.daily_briefing_job_id.
If the user deletes the agent from Command Center the pointer dangles;
status reports disabled and the next enable creates a fresh agent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.db.models import db
from src.utils.cron import daily_cron, daily_cron_time
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.db.models import Conversation, StandingChat, User

logger = get_logger(__name__)


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
5. If the get_route tool is available AND the first calendar event has
   a physical location: read the user's home from the kv_store tool
   (namespace "places", key "home"); when home exists, call
   get_route(origin="home", destination=<event location>, mode="car")
   and include a "leave by HH:MM" hint (event start minus route
   duration, minus a 10-minute buffer). Skip silently when there is no
   home place, no located event, or the tool is unavailable

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
- Close with one concrete recommendation for how to structure the day.
  On weekends (Saturday/Sunday) do NOT suggest work or professional
  deep-work blocks - steer the day toward rest, personal projects,
  family, errands and recovery unless the user's own calendar already
  has work events on it

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


def resolve_standing_instructions(conv: Conversation) -> str | None:
    """A standing chat's effective instructions (see effective_instructions)."""
    return effective_instructions(conv.standing_instructions, conv.standing_type)


def effective_instructions(instructions: str | None, standing_type: str | None) -> str | None:
    """The stored instructions, else the stock prompt for a built-in's
    standing_type (improvements arrive with deploys)."""
    if instructions:
        return instructions
    if standing_type:
        return SYSTEM_AGENT_PROMPTS.get(standing_type)
    return None


def _resolve_briefing(user: User) -> StandingChat | None:
    if not user.daily_briefing_job_id:
        return None
    return db.get_standing_chat(user.daily_briefing_job_id, user.id)


def get_briefing_status(user: User) -> dict[str, object]:
    """Settings view of the briefing: {enabled, time, timezone}."""
    briefing = _resolve_briefing(user)
    if not briefing:
        return {"enabled": False, "time": DEFAULT_BRIEFING_TIME, "timezone": "UTC"}
    schedule = briefing.job.schedule
    return {
        "enabled": briefing.enabled and bool(schedule),
        "time": daily_cron_time(schedule) or DEFAULT_BRIEFING_TIME,
        "timezone": briefing.job.timezone or "UTC",
    }


def set_briefing(user: User, enabled: bool, time_str: str, timezone: str) -> dict[str, object]:
    """Create or update the briefing agent to match the Settings values.

    Returns the resulting status dict (same shape as get_briefing_status).
    """
    schedule = daily_cron(time_str)
    briefing = _resolve_briefing(user)

    if briefing is None:
        if not enabled:
            # Nothing to do - don't create a disabled agent
            return {"enabled": False, "time": time_str, "timezone": timezone}
        briefing = db.create_standing_chat(
            user.id,
            BRIEFING_AGENT_NAME,
            # NULL = stock prompt, resolved from code at run time (see
            # resolve_standing_instructions) so improvements ship with
            # deploys; the editor stores a value only on customization
            None,
            description=BRIEFING_AGENT_DESCRIPTION,
            schedule=schedule,
            timezone=timezone,
            grants=None,  # all tools (calendar, todoist, garmin, ...)
            # Briefings are independent reports - never feed yesterday's
            # run back into the LLM
            fresh_context=True,
            standing_type=SYSTEM_TYPE_DAILY_BRIEFING,
        )
        db.update_user_daily_briefing_job(user.id, briefing.id)
        logger.info(
            "Daily briefing created",
            extra={"user_id": user.id, "job_id": briefing.id, "time": time_str},
        )
    else:
        db.update_standing_chat(
            briefing.id,
            user.id,
            schedule=schedule,
            timezone=timezone,
            enabled=enabled,
            # Enforced for the settings-managed briefing: independent
            # runs, and unrestricted tools (the briefing needs calendar/
            # tasks/Garmin; this also self-heals agents that lost their
            # tools to the old editor trap)
            fresh_context=True,
            grants=None,
        )
        logger.info(
            "Daily briefing updated",
            extra={
                "user_id": user.id,
                "job_id": briefing.id,
                "enabled": enabled,
                "time": time_str,
            },
        )

    return {"enabled": enabled, "time": time_str, "timezone": timezone}
