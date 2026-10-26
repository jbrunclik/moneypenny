"""Stored timestamps: one place that knows every format the database holds.

Columns hold one of two legacy naive formats (see src/utils/datetime_utils.py):
``"local"`` (host wall-clock time - conversation data, costs) or ``"utc"``
(UTC-naive - agents, caches, kv_store, settings). Once the data migration
converts them, every column holds fixed-width UTC with an explicit offset
(``YYYY-MM-DDTHH:MM:SS.ffffff+00:00``) and the app_settings flag
``timestamp_storage`` reads ``utc``.

- ``from_db`` reads any of them (naive per the column's legacy zone, ``Z``,
  any offset) into an aware UTC datetime.
- ``to_db`` writes the column's legacy format until the flag says ``utc``,
  then the fixed-width UTC format.
- ``app_local_date`` (SQL) gives a stored value's APP_TIMEZONE calendar date,
  for day buckets in queries; ``register_sql_functions`` installs it on every
  pooled connection.

Naive local values are read with the zone's full DST rules
(``LEGACY_TIMESTAMP_TIMEZONE``, else the host zone from /etc/localtime), never
a fixed offset. A value in the repeated fall-back hour reads as its first
occurrence (``fold=0``).
"""

import sqlite3
from datetime import UTC, datetime, tzinfo
from functools import cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.config import Config
from src.utils.clock import app_tz, to_api
from src.utils.logging import get_logger

logger = get_logger(__name__)

type LegacyFormat = Literal["local", "utc"]

# app_settings key the data migration sets to "utc" once every column holds
# offset-carrying UTC values
TIMESTAMP_STORAGE_SETTING = "timestamp_storage"
_UTC_STORAGE = "utc"
_HOST_LOCALTIME = Path("/etc/localtime")

# Database files whose flag already reads "utc" - it never flips back, so each
# process reads it until it does and then stops asking
# per-worker: a cache of a one-way flag; every worker reads it from the DB itself
_utc_storage_files: set[str] = set()


def _zone_from_localtime(path: Path) -> tzinfo:
    """The zone a localtime file names: its IANA key when it links into a
    zoneinfo tree (so the name shows up in logs), else the file's own rules."""
    parts = path.resolve().parts
    if "zoneinfo" in parts:
        start = len(parts) - parts[::-1].index("zoneinfo")
        try:
            return ZoneInfo("/".join(parts[start:]))
        except ZoneInfoNotFoundError, ValueError:
            logger.debug("localtime target is not a zoneinfo key", extra={"path": str(path)})
    with path.open("rb") as zone_file:
        return ZoneInfo.from_file(zone_file, key="localtime")


@cache
def _host_zone() -> tzinfo:
    try:
        return _zone_from_localtime(_HOST_LOCALTIME)
    except OSError, ValueError:
        logger.warning("Host timezone unreadable, reading legacy local timestamps as UTC")
        return UTC


def legacy_local_zone() -> tzinfo:
    """The zone naive ``"local"`` values were written in."""
    if Config.LEGACY_TIMESTAMP_TIMEZONE:
        return ZoneInfo(Config.LEGACY_TIMESTAMP_TIMEZONE)
    return _host_zone()


def _legacy_zone(legacy: LegacyFormat) -> tzinfo:
    return legacy_local_zone() if legacy == "local" else UTC


def from_db(value: str, legacy: LegacyFormat) -> datetime:
    """Parse a stored timestamp into an aware UTC datetime.

    Accepts naive ISO strings (in the column's ``legacy`` zone, ``T`` or space
    separated, with or without microseconds), ``Z`` and any ``+HH:MM`` offset.
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_legacy_zone(legacy))
    return parsed.astimezone(UTC)


def _database_file(conn: sqlite3.Connection) -> str:
    """The main database's file path ('' for in-memory and temp databases)."""
    for row in conn.execute("PRAGMA database_list").fetchall():
        if row[1] == "main":
            return str(row[2] or "")
    return ""


def _read_storage_flag(conn: sqlite3.Connection) -> str | None:
    try:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (TIMESTAMP_STORAGE_SETTING,)
        ).fetchone()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return None
        raise
    return str(row[0]) if row else None


def stores_utc(conn: sqlite3.Connection) -> bool:
    """Whether this database stores offset-carrying UTC (the flag is set)."""
    db_file = _database_file(conn)
    if db_file and db_file in _utc_storage_files:
        return True
    if _read_storage_flag(conn) != _UTC_STORAGE:
        return False
    if db_file:
        _utc_storage_files.add(db_file)
    return True


def to_db(dt: datetime, legacy: LegacyFormat, conn: sqlite3.Connection) -> str:
    """Format an aware datetime for a column whose legacy format is ``legacy``.

    Until the migration sets the flag: the legacy naive format, exactly as the
    app writes it today (``isoformat()``). After: fixed-width UTC, the same
    string the API sends.
    """
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"naive datetime {dt.isoformat()} - pass an aware one")
    if stores_utc(conn):
        return to_api(dt)
    return dt.astimezone(_legacy_zone(legacy)).replace(tzinfo=None).isoformat()


def normalize_cursor(timestamp: str, legacy: LegacyFormat, conn: sqlite3.Connection) -> str:
    """Rewrite a pagination cursor's timestamp in the column's current format.

    Cursors are compared with stored values as strings, and a client may hold
    one minted before the flag switched (or built from a parsed datetime's
    variable-width ``isoformat()``), so bring it to the stored format first.
    """
    return to_db(from_db(timestamp, legacy), legacy, conn)


def app_local_date(value: str | None, legacy: str) -> str | None:
    """SQL ``app_local_date(ts, legacy)``: the APP_TIMEZONE date (YYYY-MM-DD).

    NULL (and a value that is not a timestamp) gives NULL, like SQLite's own
    date functions; an unknown ``legacy`` is an error.
    """
    if value is None:
        return None
    if legacy not in ("local", "utc"):
        raise ValueError(f"app_local_date: legacy must be 'local' or 'utc', got {legacy!r}")
    kind: LegacyFormat = "local" if legacy == "local" else "utc"
    try:
        instant = from_db(value, kind)
    except ValueError:
        return None
    return instant.astimezone(app_tz()).date().isoformat()


def register_sql_functions(conn: sqlite3.Connection) -> None:
    """Install the timestamp SQL functions on a connection (the pool calls it)."""
    conn.create_function("app_local_date", 2, app_local_date, deterministic=True)
