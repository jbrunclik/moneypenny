"""Stored timestamps: one format, and the helpers that read and write it.

Every timestamp column holds fixed-width UTC with an explicit offset
(``YYYY-MM-DDTHH:MM:SS.ffffff+00:00``) - the same string the API sends, so
stored values sort chronologically as plain strings. Migration 0072 converted
the two older naive formats (host wall-clock time and UTC-naive).

- ``from_db`` reads a stored value into an aware UTC datetime; a value
  without an offset is an error.
- ``to_db`` writes an aware datetime in the stored format.
- ``app_local_date`` (SQL) gives a stored value's APP_TIMEZONE calendar date,
  for day buckets in queries; ``register_sql_functions`` installs it on every
  pooled connection.
"""

import sqlite3
from datetime import UTC, datetime

from src.utils.clock import app_tz, to_api


def from_db(value: str) -> datetime:
    """Parse a stored timestamp into an aware UTC datetime.

    Accepts ``Z`` and any ``+HH:MM`` offset; raises ValueError for a value
    without one.
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"stored timestamp {value!r} has no offset")
    return parsed.astimezone(UTC)


def from_db_or_none(value: str | None) -> datetime | None:
    """``from_db`` for a nullable column (NULL and '' read as None)."""
    return from_db(value) if value else None


def to_db(dt: datetime) -> str:
    """Format an aware datetime as stored: fixed-width UTC."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"naive datetime {dt.isoformat()} - pass an aware one")
    return to_api(dt)


def to_db_or_none(dt: datetime | None) -> str | None:
    """``to_db`` for a nullable column."""
    return to_db(dt) if dt is not None else None


def normalize_cursor(timestamp: str) -> str:
    """Rewrite a pagination cursor's timestamp in the stored format.

    Cursors are compared with stored values as strings, and a client may send
    one in another width or zone (``Z``, no microseconds), so bring it to the
    stored format first.
    """
    return to_db(from_db(timestamp))


def app_local_date(value: str | None) -> str | None:
    """SQL ``app_local_date(ts)``: the APP_TIMEZONE date (YYYY-MM-DD).

    NULL (and a value that is not a timestamp) gives NULL, like SQLite's own
    date functions.
    """
    if value is None:
        return None
    try:
        instant = from_db(value)
    except ValueError:
        return None
    return instant.astimezone(app_tz()).date().isoformat()


def register_sql_functions(conn: sqlite3.Connection) -> None:
    """Install the timestamp SQL functions on a connection (the pool calls it)."""
    conn.create_function("app_local_date", 1, app_local_date, deterministic=True)
