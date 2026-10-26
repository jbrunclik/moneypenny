"""Date parsing and day naming for the planner dashboard."""

from datetime import datetime


def day_name(date: datetime, today: datetime) -> str:
    """Get a human-readable name for a day relative to today."""
    days_diff = (date.date() - today.date()).days
    if days_diff == 0:
        return "Today"
    if days_diff == 1:
        return "Tomorrow"
    return date.strftime("%A")  # Full weekday name


def parse_date(date_str: str | None) -> datetime | None:
    """Parse a date string (YYYY-MM-DD) to datetime."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None


def parse_datetime(datetime_str: str | None) -> datetime | None:
    """Parse an ISO datetime string to datetime."""
    if not datetime_str:
        return None
    try:
        # Handle timezone-aware strings
        if datetime_str.endswith("Z"):
            datetime_str = datetime_str[:-1] + "+00:00"
        return datetime.fromisoformat(datetime_str)
    except ValueError:
        return None
