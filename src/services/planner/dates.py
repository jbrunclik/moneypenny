"""Date parsing and day naming for the planner dashboard.

Days are calendar dates in APP_TIMEZONE: a timed value (an event start, a
forecast period) lands on its local date, not on the date of whatever offset
it was written in.
"""

from datetime import date, datetime

from src.utils.clock import to_local


def day_name(day: date, today: date) -> str:
    """Get a human-readable name for a day relative to today."""
    days_diff = (day - today).days
    if days_diff == 0:
        return "Today"
    if days_diff == 1:
        return "Tomorrow"
    return day.strftime("%A")  # Full weekday name


def parse_date(date_str: str | None) -> date | None:
    """Parse a date string (YYYY-MM-DD)."""
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        return None


def local_date_of(datetime_str: str | None) -> date | None:
    """The APP_TIMEZONE calendar date of an ISO datetime.

    A value with an offset (or ``Z``) is converted; one without is already a
    local wall-clock time (an integration's floating time) and keeps its date.
    """
    if not datetime_str:
        return None
    try:
        # tz-naive: a value without an offset is a local wall time by contract
        parsed = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (to_local(parsed) if parsed.tzinfo else parsed).date()
