"""Reminder instants and recurring cron strings, built by code.

The schedule tool's model fills structured fields (a date and a time, or days
and a time, in the household timezone); this module validates them and builds
the UTC instant or the cron string - so "Friday at 8" in Czech or English ends
up the same, and the model never writes cron or converts timezones itself.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as day_time
from zoneinfo import ZoneInfo

from croniter import croniter

_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DAY_NUMBERS = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
_DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
_ALIASES = {"daily": "*", "weekdays": "1-5", "weekends": "0,6"}
_ALIAS_TEXT = {"*": "every day", "1-5": "every weekday", "0,6": "every weekend day"}
# How often a watcher may check: never more often than every 6 hours
_WATCH_INTERVALS = {"6h": 6, "daily": 24, "weekly": 168}
_HOURS_PER_DAY = 24


@dataclass(frozen=True)
class ScheduleError:
    """Why the fields do not make a schedule (returned, not raised)."""

    message: str


def _parse_time(time: str) -> tuple[int, int] | None:
    match = _TIME.match(time.strip())
    return (int(match.group(1)), int(match.group(2))) if match else None


def one_off_instant(day: str, time: str, tz: str, now: datetime) -> datetime | ScheduleError:
    """The UTC instant of `day` (YYYY-MM-DD) at `time` (HH:MM) in `tz`."""
    hm = _parse_time(time)
    if not _DATE.match(day.strip()) or hm is None:
        return ScheduleError(f"Use date as YYYY-MM-DD and time as HH:MM (got {day!r} {time!r}).")
    try:
        parsed = date.fromisoformat(day.strip())
    except ValueError:
        return ScheduleError(f"{day!r} is not a calendar date.")
    zone = ZoneInfo(tz)
    instant = datetime(parsed.year, parsed.month, parsed.day, *hm, tzinfo=zone).astimezone(UTC)
    if instant <= now:
        local_now = now.astimezone(zone).strftime("%a %d %b %Y %H:%M")
        return ScheduleError(f"That time has passed - it is now {local_now} ({tz}).")
    return instant


def recurring_cron(days: list[str], time: str) -> ScheduleError | str:
    """A cron string for `time` on `days` (mon..sun, or daily/weekdays/weekends)."""
    hm = _parse_time(time)
    if hm is None:
        return ScheduleError(f"Use time as HH:MM (got {time!r}).")
    names = [
        d.strip().lower()[:3] if d.strip().lower() not in _ALIASES else d.strip().lower()
        for d in days
    ]
    if not names:
        return ScheduleError("Give at least one day (mon..sun, daily, weekdays or weekends).")
    if len(names) == 1 and names[0] in _ALIASES:
        dow = _ALIASES[names[0]]
    elif all(n in _DAY_NUMBERS for n in names):
        dow = ",".join(str(n) for n in sorted({_DAY_NUMBERS[n] for n in names}))
    else:
        return ScheduleError(f"Unknown day in {days!r}: use mon..sun, daily, weekdays or weekends.")
    return f"{hm[1]} {hm[0]} * * {dow}"


def describe_instant(instant: datetime, tz: str) -> str:
    """'Fri 13 Nov 2026 08:00' in the household timezone."""
    return instant.astimezone(ZoneInfo(tz)).strftime("%a %d %b %Y %H:%M")


def describe_cron(cron: str) -> str:
    """'every Monday at 09:00' for a cron string recurring_cron built."""
    minute, hour, _, _, dow = cron.split()
    at = f"{int(hour):02d}:{int(minute):02d}"
    if dow in _ALIAS_TEXT:
        return f"{_ALIAS_TEXT[dow]} at {at}"
    days = [_DAY_NAMES[int(n)] for n in dow.split(",")]
    return f"every {' and '.join(days)} at {at}"


def watch_interval_hours(hint: str) -> int | ScheduleError:
    """Hours between a watcher's checks: 6h, daily or weekly."""
    hours = _WATCH_INTERVALS.get(hint.strip().lower())
    if hours is None:
        return ScheduleError(f"interval must be 6h, daily or weekly (got {hint!r}).")
    return hours


def until_instant(day: str, tz: str, now: datetime) -> datetime | ScheduleError:
    """The UTC instant `day` (YYYY-MM-DD) ends in `tz`; a past day is refused."""
    if not _DATE.match(day.strip()):
        return ScheduleError(f"Use the end date as YYYY-MM-DD (got {day!r}).")
    try:
        parsed = date.fromisoformat(day.strip())
    except ValueError:
        return ScheduleError(f"{day!r} is not a calendar date.")
    end = datetime.combine(parsed, day_time(23, 59, 59), tzinfo=ZoneInfo(tz)).astimezone(UTC)
    if end <= now:
        return ScheduleError(f"{day} has already passed.")
    return end


def describe_interval(hours: int) -> str:
    """'every 6 hours', 'daily', 'weekly' or 'every N days'."""
    if hours == _HOURS_PER_DAY:
        return "daily"
    if hours == _WATCH_INTERVALS["weekly"]:
        return "weekly"
    if hours % _HOURS_PER_DAY == 0:
        return f"every {hours // _HOURS_PER_DAY} days"
    return f"every {hours} hours"


def next_cron_run(cron: str, tz: str, after: datetime) -> datetime:
    """The first UTC instant after `after` that matches `cron` in `tz`."""
    nxt: datetime = croniter(cron, after.astimezone(ZoneInfo(tz))).get_next(datetime)
    return nxt.astimezone(UTC)
