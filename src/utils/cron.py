"""Daily cron schedules: an "HH:MM" time and its `M H * * *` cron line."""

import re

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def daily_cron(time_str: str) -> str:
    """'07:30' -> '30 7 * * *'."""
    match = _TIME_RE.match(time_str)
    if not match:
        raise ValueError(f"Invalid time: {time_str!r}")
    hour, minute = int(match.group(1)), int(match.group(2))
    return f"{minute} {hour} * * *"


def daily_cron_time(cron: str | None) -> str | None:
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
