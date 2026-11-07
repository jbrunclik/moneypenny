"""src/db/models/timestamps.py: the stored timestamp format in and out.

APP_TIMEZONE is Europe/Prague. 2026 transitions: Mar 29 01:00Z (02:00 CET ->
03:00 CEST) and Oct 25 01:00Z (03:00 CEST -> 02:00 CET).
"""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest

from src.config import Config
from src.db.models.timestamps import (
    from_db,
    from_db_or_none,
    normalize_cursor,
    register_sql_functions,
    to_db,
    to_db_or_none,
)

if TYPE_CHECKING:
    from src.db.models import Database

PRAGUE = ZoneInfo("Europe/Prague")


def _z(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _prague(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "APP_TIMEZONE", "Europe/Prague")


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A file database with the SQL functions."""
    connection = sqlite3.connect(tmp_path / "ts.db")
    register_sql_functions(connection)
    yield connection
    connection.close()


class TestFromDb:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2026-07-15T10:00:00.000000+00:00", _z(2026, 7, 15, 10)),
            ("2026-07-15T10:00:00+00:00", _z(2026, 7, 15, 10)),
            ("2026-07-15T10:00:00Z", _z(2026, 7, 15, 10)),
            ("2026-07-15T10:00:00.000001Z", _z(2026, 7, 15, 10, 0, 0, 1)),
            ("2026-07-15T10:00:00+02:00", _z(2026, 7, 15, 8)),
            ("2026-07-15T10:00:00.250000+02:00", _z(2026, 7, 15, 8, 0, 0, 250000)),
            ("2026-01-15T10:00:00-05:00", _z(2026, 1, 15, 15)),
            ("2026-10-25 02:30:00+00:00", _z(2026, 10, 25, 2, 30)),
        ],
    )
    def test_reads_aware_utc(self, value: str, expected: datetime) -> None:
        parsed = from_db(value)
        assert parsed == expected
        assert parsed.tzinfo is UTC

    @pytest.mark.parametrize("value", ["2026-01-15T10:00:00", "2026-01-15 10:00:00.123456"])
    def test_rejects_naive(self, value: str) -> None:
        with pytest.raises(ValueError, match="no offset"):
            from_db(value)

    def test_rejects_garbage(self) -> None:
        with pytest.raises(ValueError, match="Invalid isoformat"):
            from_db("yesterday")


class TestNullable:
    def test_from_db_or_none(self) -> None:
        assert from_db_or_none(None) is None
        assert from_db_or_none("") is None
        assert from_db_or_none("2026-01-15T09:00:00Z") == _z(2026, 1, 15, 9)

    def test_to_db_or_none(self) -> None:
        assert to_db_or_none(None) is None
        assert to_db_or_none(_z(2026, 1, 15, 9)) == "2026-01-15T09:00:00.000000+00:00"


class TestToDb:
    @pytest.mark.parametrize(
        ("dt", "expected"),
        [
            (_z(2026, 1, 15, 9), "2026-01-15T09:00:00.000000+00:00"),
            (_z(2026, 7, 15, 8, 0, 0, 1), "2026-07-15T08:00:00.000001+00:00"),
            # Any aware zone in, UTC out
            (datetime(2026, 7, 15, 10, tzinfo=PRAGUE), "2026-07-15T08:00:00.000000+00:00"),
        ],
    )
    def test_writes_fixed_width_utc(self, dt: datetime, expected: str) -> None:
        assert to_db(dt) == expected

    @pytest.mark.parametrize(
        "dt",
        [
            _z(2026, 1, 15, 9),
            _z(2026, 3, 29, 1, 0, 0, 1),
            _z(2026, 7, 15, 8, 0, 0, 123456),
            # Both 02:30s of the fall-back night stay apart
            _z(2026, 10, 25, 0, 30),
            _z(2026, 10, 25, 1, 30),
        ],
    )
    def test_round_trips(self, dt: datetime) -> None:
        assert from_db(to_db(dt)) == dt

    def test_sorts_chronologically_as_strings(self) -> None:
        instants = [_z(2026, 10, 25, 0, 30), _z(2026, 10, 25, 1, 30), _z(2026, 10, 25, 1, 30, 0, 1)]
        stored = [to_db(dt.astimezone(PRAGUE)) for dt in instants]
        assert sorted(stored) == stored

    def test_rejects_naive(self) -> None:
        with pytest.raises(ValueError, match="naive"):
            to_db(datetime(2026, 1, 15, 9))

    def test_a_migrated_app_database_has_no_storage_flag(self, test_database: Database) -> None:
        # Migration 0074 drops the flag 0072 set
        assert test_database.get_setting("timestamp_storage") is None


class TestNormalizeCursor:
    @pytest.mark.parametrize(
        "cursor",
        [
            "2026-01-15T09:00:00+00:00",  # variable-width isoformat()
            "2026-01-15T09:00:00Z",
            "2026-01-15T10:00:00+01:00",
            "2026-01-15T09:00:00.000000+00:00",
        ],
    )
    def test_stored_format(self, cursor: str) -> None:
        assert normalize_cursor(cursor) == "2026-01-15T09:00:00.000000+00:00"

    def test_rejects_naive(self) -> None:
        with pytest.raises(ValueError, match="no offset"):
            normalize_cursor("2026-01-15T10:00:00")


def _local_date(conn: sqlite3.Connection, value: str | None) -> str | None:
    row = conn.execute("SELECT app_local_date(?)", (value,)).fetchone()
    result: str | None = row[0]
    return result


class TestAppLocalDateSql:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            # Near local midnight (CET: +1, CEST: +2)
            ("2026-10-25T22:59:59.000000+00:00", "2026-10-25"),
            ("2026-10-25T23:00:00Z", "2026-10-26"),
            ("2026-07-15T21:59:59.999999+00:00", "2026-07-15"),
            ("2026-07-15T22:00:00+00:00", "2026-07-16"),
            ("2026-03-28T23:00:00+00:00", "2026-03-29"),
            ("2026-03-29T22:00:00+00:00", "2026-03-30"),
            ("2026-07-16T00:30:00+02:00", "2026-07-16"),
            ("2026-07-15T18:30:00-04:00", "2026-07-16"),
            ("2026-12-31T23:00:00.000000+00:00", "2027-01-01"),
        ],
    )
    def test_local_day(self, conn: sqlite3.Connection, value: str, expected: str) -> None:
        assert _local_date(conn, value) == expected

    def test_null_naive_and_garbage_give_null(self, conn: sqlite3.Connection) -> None:
        assert _local_date(conn, None) is None
        assert _local_date(conn, "2026-10-25T23:30:00") is None
        assert _local_date(conn, "not a timestamp") is None

    def test_follows_app_timezone(
        self, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Config, "APP_TIMEZONE", "Pacific/Chatham")  # +13:45 in October
        assert _local_date(conn, "2026-10-25T10:15:00+00:00") == "2026-10-26"

    def test_groups_by_local_day(self, conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE events (ts TEXT)")
        rows = [
            ("2026-10-25T23:30:00.000000+00:00",),  # Oct 26 00:30 CET
            ("2026-10-25T23:00:00.000000+00:00",),  # Oct 26 00:00 CET
            ("2026-10-25T22:59:59Z",),  # Oct 25 23:59:59 CET
            ("2026-10-25T00:30:00+00:00",),  # Oct 25 02:30 CEST
        ]
        conn.executemany("INSERT INTO events VALUES (?)", rows)
        grouped = conn.execute(
            "SELECT app_local_date(ts) AS day, COUNT(*) FROM events GROUP BY day ORDER BY day"
        ).fetchall()
        assert grouped == [("2026-10-25", 2), ("2026-10-26", 2)]

    def test_usable_in_an_index(self, conn: sqlite3.Connection) -> None:
        """Deterministic, so SQLite accepts it in an expression index."""
        conn.execute("CREATE TABLE events (ts TEXT)")
        conn.execute("CREATE INDEX events_day ON events (app_local_date(ts))")

    def test_registered_on_every_pooled_connection(self, test_database: Database) -> None:
        import threading

        results: list[str | None] = []

        def query() -> None:
            with test_database._pool.get_connection() as pooled:
                results.append(_local_date(pooled, "2026-07-15T22:00:00+00:00"))

        query()
        worker = threading.Thread(target=query)  # a new thread gets a new connection
        worker.start()
        worker.join()
        assert results == ["2026-07-16", "2026-07-16"]
