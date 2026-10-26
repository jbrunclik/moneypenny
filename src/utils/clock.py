"""The current time and the household's day boundaries, timezone-aware.

Everything here returns or takes AWARE datetimes. Instants are UTC; day
boundaries (midnight, the planner's 4am, month starts) are drawn in
``Config.APP_TIMEZONE`` and returned as UTC instants, so they compare directly
with stored timestamps read through ``src.db.models.timestamps.from_db``.

DST: local wall-clock times are built from a calendar date plus a time and
resolved by zoneinfo (``fold=0``), never by ``replace(hour=...)`` on a UTC
value. A wall time in the repeated fall-back hour resolves to its first
occurrence; one inside a spring-forward gap takes the offset from before the
gap (PEP 495), so a boundary at the very start of a gap lands on the
transition instant. In Europe/Prague neither midnight nor 04:00 is ever
skipped or repeated (the clocks change at 02:00/03:00).

Tests move time through the ``_now()`` seam (patch ``src.utils.clock._now``),
not by patching ``time.time`` - that also shifts ``date.today()``.
"""

from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from zoneinfo import ZoneInfo

from src.config import Config
from src.constants import PLANNER_RESET_HOUR

# Fixed width so stored and serialized values compare as strings: isoformat()
# drops the fraction when microseconds == 0, and "+" sorts before "."
_UTC_FORMAT = "%Y-%m-%dT%H:%M:%S.%f+00:00"


def _now() -> datetime:
    """The clock seam: tests patch this, not the global time."""
    return datetime.now(UTC)


def utc_now() -> datetime:
    """The current instant, aware, in UTC."""
    return _now()


@cache
def _zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def app_tz() -> ZoneInfo:
    """The household's timezone (``Config.APP_TIMEZONE``)."""
    return _zone(Config.APP_TIMEZONE)


def _require_aware(dt: datetime) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"naive datetime {dt.isoformat()} - pass an aware one")


def _local_instant(day: date, wall: time) -> datetime:
    """The UTC instant of a wall-clock time on a local calendar day."""
    return datetime.combine(day, wall, tzinfo=app_tz()).astimezone(UTC)


def local_today(now: datetime | None = None) -> date:
    """Today's calendar date in APP_TIMEZONE (at ``now``, default: now)."""
    moment = now if now is not None else utc_now()
    _require_aware(moment)
    return moment.astimezone(app_tz()).date()


def local_day_start(dt: datetime) -> datetime:
    """The start of ``dt``'s local day in APP_TIMEZONE, as an aware UTC instant."""
    _require_aware(dt)
    return _local_instant(dt.astimezone(app_tz()).date(), time.min)


def local_month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """A local calendar month as aware UTC instants ``[start, end)``."""
    first = date(year, month, 1)
    next_first = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return _local_instant(first, time.min), _local_instant(next_first, time.min)


def planner_cutoff(now: datetime) -> datetime:
    """The most recent local PLANNER_RESET_HOUR:00 at or before ``now``, in UTC.

    A planner last reset before this instant is due for its daily reset.
    """
    _require_aware(now)
    reset_time = time(PLANNER_RESET_HOUR)
    today = now.astimezone(app_tz()).date()
    cutoff = _local_instant(today, reset_time)
    if cutoff > now:
        cutoff = _local_instant(today - timedelta(days=1), reset_time)
    return cutoff


def to_api(dt: datetime) -> str:
    """Serialize an instant for the API: fixed-width ISO 8601 in UTC.

    Always ``YYYY-MM-DDTHH:MM:SS.ffffff+00:00`` (six fraction digits even when
    they are zero), so browsers parse it timezone-correctly and the strings
    sort chronologically.
    """
    _require_aware(dt)
    return dt.astimezone(UTC).strftime(_UTC_FORMAT)
