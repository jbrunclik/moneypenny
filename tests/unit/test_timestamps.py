"""src/db/models/timestamps.py: every stored timestamp format in and out.

Legacy local values are read in Europe/Prague (pinned through
LEGACY_TIMESTAMP_TIMEZONE so the host zone doesn't matter); APP_TIMEZONE is
Europe/Prague too. 2026 transitions: Mar 29 01:00Z (02:00 CET -> 03:00 CEST)
and Oct 25 01:00Z (03:00 CEST -> 02:00 CET).
"""

import shutil
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, tzinfo
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest

from src.config import Config
from src.db.models import timestamps
from src.db.models.timestamps import (
    TIMESTAMP_STORAGE_SETTING,
    LegacyFormat,
    from_db,
    from_db_or_none,
    legacy_local_zone,
    normalize_cursor,
    register_sql_functions,
    stores_utc,
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
    monkeypatch.setattr(Config, "LEGACY_TIMESTAMP_TIMEZONE", "Europe/Prague")


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A file database with the app_settings table and the SQL functions."""
    connection = sqlite3.connect(tmp_path / "ts.db")
    connection.execute("CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT)")
    register_sql_functions(connection)
    yield connection
    connection.close()


def _set_flag(conn: sqlite3.Connection, value: str | None) -> None:
    conn.execute("DELETE FROM app_settings WHERE key = ?", (TIMESTAMP_STORAGE_SETTING,))
    if value is not None:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?)",
            (TIMESTAMP_STORAGE_SETTING, value),
        )
    conn.commit()


class TestFromDb:
    @pytest.mark.parametrize(
        ("value", "legacy", "expected"),
        [
            # Naive local (CET in winter, CEST in summer), T or space, +- micros
            ("2026-01-15T10:00:00", "local", _z(2026, 1, 15, 9)),
            ("2026-01-15 10:00:00", "local", _z(2026, 1, 15, 9)),
            ("2026-07-15T10:00:00.123456", "local", _z(2026, 7, 15, 8, 0, 0, 123456)),
            ("2026-07-15T10:00:00", "local", _z(2026, 7, 15, 8)),
            # Around the spring-forward
            ("2026-03-29T01:59:59", "local", _z(2026, 3, 29, 0, 59, 59)),
            ("2026-03-29T03:00:00", "local", _z(2026, 3, 29, 1)),
            # The skipped 02:30 reads with the pre-gap offset (fold=0)
            ("2026-03-29T02:30:00", "local", _z(2026, 3, 29, 1, 30)),
            # The repeated fall-back hour reads as its first occurrence (CEST)
            ("2026-10-25T02:30:00", "local", _z(2026, 10, 25, 0, 30)),
            ("2026-10-25T02:30:00.500000", "local", _z(2026, 10, 25, 0, 30, 0, 500000)),
            ("2026-10-25T03:00:00", "local", _z(2026, 10, 25, 2)),
            # Naive UTC
            ("2026-01-15T10:00:00", "utc", _z(2026, 1, 15, 10)),
            ("2026-07-15T10:00:00.123456", "utc", _z(2026, 7, 15, 10, 0, 0, 123456)),
            ("2026-10-25 02:30:00", "utc", _z(2026, 10, 25, 2, 30)),
            # Explicit offsets win over the column's legacy zone
            ("2026-07-15T10:00:00Z", "local", _z(2026, 7, 15, 10)),
            ("2026-07-15T10:00:00.000001Z", "utc", _z(2026, 7, 15, 10, 0, 0, 1)),
            ("2026-07-15T10:00:00+00:00", "local", _z(2026, 7, 15, 10)),
            ("2026-07-15T10:00:00.000000+00:00", "utc", _z(2026, 7, 15, 10)),
            ("2026-07-15T10:00:00+02:00", "local", _z(2026, 7, 15, 8)),
            ("2026-07-15T10:00:00.250000+02:00", "utc", _z(2026, 7, 15, 8, 0, 0, 250000)),
            ("2026-01-15T10:00:00-05:00", "local", _z(2026, 1, 15, 15)),
        ],
    )
    def test_reads_aware_utc(self, value: str, legacy: LegacyFormat, expected: datetime) -> None:
        parsed = from_db(value, legacy)
        assert parsed == expected
        assert parsed.tzinfo is UTC

    def test_rejects_garbage(self) -> None:
        with pytest.raises(ValueError, match="Invalid isoformat"):
            from_db("yesterday", "utc")

    def test_local_uses_full_dst_rules_not_a_fixed_offset(self) -> None:
        winter = from_db("2026-01-15T12:00:00", "local")
        summer = from_db("2026-07-15T12:00:00", "local")
        assert (winter.hour, summer.hour) == (11, 10)


class TestNullable:
    def test_from_db_or_none(self) -> None:
        assert from_db_or_none(None, "utc") is None
        assert from_db_or_none("", "utc") is None
        assert from_db_or_none("2026-01-15T09:00:00", "utc") == _z(2026, 1, 15, 9)

    def test_to_db_or_none(self, conn: sqlite3.Connection) -> None:
        assert to_db_or_none(None, "utc", conn) is None
        assert to_db_or_none(_z(2026, 1, 15, 9), "utc", conn) == "2026-01-15T09:00:00"


class TestLegacyLocalZone:
    def test_config_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Config, "LEGACY_TIMESTAMP_TIMEZONE", "America/New_York")
        assert legacy_local_zone() == ZoneInfo("America/New_York")
        assert from_db("2026-07-15T10:00:00", "local") == _z(2026, 7, 15, 14)

    def test_empty_config_uses_the_host_zone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Config, "LEGACY_TIMESTAMP_TIMEZONE", "")
        host: tzinfo = ZoneInfo("Asia/Tokyo")
        monkeypatch.setattr(timestamps, "_host_zone", lambda: host)
        assert legacy_local_zone() is host
        assert from_db("2026-07-15T10:00:00", "local") == _z(2026, 7, 15, 1)

    def _tzdata_file(self, key: str) -> Path:
        return Path(str(files("tzdata").joinpath("zoneinfo", *key.split("/"))))

    def test_localtime_symlink_resolves_to_its_iana_key(self, tmp_path: Path) -> None:
        link = tmp_path / "localtime"
        link.symlink_to(self._tzdata_file("Europe/Prague"))
        zone = timestamps._zone_from_localtime(link)
        assert zone == ZoneInfo("Europe/Prague")

    def test_localtime_copy_keeps_its_dst_rules(self, tmp_path: Path) -> None:
        """A plain file (no zoneinfo path to name it) is read with its own rules."""
        copy = tmp_path / "localtime"
        shutil.copy(self._tzdata_file("Europe/Prague"), copy)
        zone = timestamps._zone_from_localtime(copy)
        winter = datetime(2026, 1, 15, 12, tzinfo=zone)
        summer = datetime(2026, 7, 15, 12, tzinfo=zone)
        assert (winter.utcoffset(), summer.utcoffset()) == (
            PRAGUE.utcoffset(winter.replace(tzinfo=None)),
            PRAGUE.utcoffset(summer.replace(tzinfo=None)),
        )
        assert str(winter.utcoffset()) != str(summer.utcoffset())

    def test_host_zone_has_dst_rules(self) -> None:
        """Whatever the host is, it reads as a zone, not a fixed offset."""
        timestamps._host_zone.cache_clear()
        assert isinstance(timestamps._host_zone(), tzinfo)


class TestToDbLegacy:
    @pytest.mark.parametrize(
        ("dt", "legacy", "expected"),
        [
            # Exactly what datetime.now().isoformat() / utcnow_naive().isoformat()
            # write today: naive, variable width
            (_z(2026, 1, 15, 9), "local", "2026-01-15T10:00:00"),
            (_z(2026, 7, 15, 8, 0, 0, 123456), "local", "2026-07-15T10:00:00.123456"),
            (_z(2026, 10, 25, 0, 30), "local", "2026-10-25T02:30:00"),  # first 02:30
            (_z(2026, 10, 25, 1, 30), "local", "2026-10-25T02:30:00"),  # repeated 02:30
            (_z(2026, 1, 15, 9), "utc", "2026-01-15T09:00:00"),
            (_z(2026, 7, 15, 8, 0, 0, 1), "utc", "2026-07-15T08:00:00.000001"),
            # Any aware zone in
            (datetime(2026, 7, 15, 10, tzinfo=PRAGUE), "utc", "2026-07-15T08:00:00"),
        ],
    )
    def test_writes_the_legacy_format(
        self, conn: sqlite3.Connection, dt: datetime, legacy: LegacyFormat, expected: str
    ) -> None:
        assert to_db(dt, legacy, conn) == expected

    @pytest.mark.parametrize("legacy", ["local", "utc"])
    @pytest.mark.parametrize(
        "dt",
        [
            _z(2026, 1, 15, 9),
            _z(2026, 3, 29, 1, 0, 0, 1),
            _z(2026, 7, 15, 8, 0, 0, 123456),
            _z(2026, 10, 24, 23, 59, 59, 999999),
        ],
    )
    def test_round_trips(
        self, conn: sqlite3.Connection, dt: datetime, legacy: LegacyFormat
    ) -> None:
        assert from_db(to_db(dt, legacy, conn), legacy) == dt

    def test_repeated_hour_is_lossy_in_local_legacy(self, conn: sqlite3.Connection) -> None:
        """Why the migration orders the repeated hour by insertion: naive local
        strings can't tell the two 02:30s apart (both read back as the first)."""
        second = _z(2026, 10, 25, 1, 30)
        assert from_db(to_db(second, "local", conn), "local") == _z(2026, 10, 25, 0, 30)

    def test_rejects_naive(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="naive"):
            to_db(datetime(2026, 1, 15, 9), "utc", conn)


class TestToDbFlag:
    @pytest.mark.parametrize("legacy", ["local", "utc"])
    def test_flag_switches_to_fixed_width_utc(
        self, conn: sqlite3.Connection, legacy: LegacyFormat
    ) -> None:
        _set_flag(conn, "utc")
        assert to_db(_z(2026, 7, 15, 8), legacy, conn) == "2026-07-15T08:00:00.000000+00:00"
        dt = _z(2026, 10, 25, 1, 30, 0, 42)
        assert from_db(to_db(dt, legacy, conn), legacy) == dt

    def test_other_flag_values_keep_the_legacy_format(self, conn: sqlite3.Connection) -> None:
        _set_flag(conn, "legacy")
        assert not stores_utc(conn)
        assert to_db(_z(2026, 1, 15, 9), "utc", conn) == "2026-01-15T09:00:00"

    def test_flag_is_read_lazily(self, conn: sqlite3.Connection) -> None:
        dt = _z(2026, 1, 15, 9)
        assert to_db(dt, "local", conn) == "2026-01-15T10:00:00"
        _set_flag(conn, "utc")
        assert to_db(dt, "local", conn) == "2026-01-15T09:00:00.000000+00:00"

    def test_utc_is_cached_per_database_file(self, conn: sqlite3.Connection) -> None:
        _set_flag(conn, "utc")
        assert stores_utc(conn)
        _set_flag(conn, None)  # the flag never flips back; the process stops asking
        assert stores_utc(conn)

    def test_legacy_is_not_cached(self, conn: sqlite3.Connection) -> None:
        assert not stores_utc(conn)
        _set_flag(conn, "utc")
        assert stores_utc(conn)

    def test_in_memory_databases_are_not_cached(self) -> None:
        memory = sqlite3.connect(":memory:")
        memory.execute("CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT)")
        _set_flag(memory, "utc")
        assert stores_utc(memory)
        _set_flag(memory, None)
        assert not stores_utc(memory)
        memory.close()

    def test_no_settings_table_means_legacy(self) -> None:
        bare = sqlite3.connect(":memory:")
        assert to_db(_z(2026, 1, 15, 9), "utc", bare) == "2026-01-15T09:00:00"
        bare.close()

    def test_flag_via_the_app_database(self, test_database: Database) -> None:
        dt = _z(2026, 1, 15, 9)
        with test_database._pool.get_connection() as pooled:
            assert to_db(dt, "local", pooled) == "2026-01-15T10:00:00"
        test_database.set_setting(TIMESTAMP_STORAGE_SETTING, "utc")
        with test_database._pool.get_connection() as pooled:
            assert to_db(dt, "local", pooled) == "2026-01-15T09:00:00.000000+00:00"


class TestNormalizeCursor:
    @pytest.mark.parametrize(
        ("cursor", "legacy", "expected"),
        [
            ("2026-01-15T10:00:00", "local", "2026-01-15T10:00:00"),
            ("2026-01-15T10:00:00.5", "local", "2026-01-15T10:00:00.500000"),
            ("2026-01-15T09:00:00+00:00", "local", "2026-01-15T10:00:00"),
            ("2026-01-15T09:00:00.000000+00:00", "utc", "2026-01-15T09:00:00"),
            ("2026-07-15T08:00:00Z", "local", "2026-07-15T10:00:00"),
        ],
    )
    def test_legacy_storage(
        self, conn: sqlite3.Connection, cursor: str, legacy: LegacyFormat, expected: str
    ) -> None:
        assert normalize_cursor(cursor, legacy, conn) == expected

    @pytest.mark.parametrize(
        ("cursor", "legacy"),
        [
            ("2026-01-15T10:00:00", "local"),  # minted before the switch
            ("2026-01-15T09:00:00", "utc"),
            ("2026-01-15T09:00:00+00:00", "utc"),  # variable-width isoformat()
            ("2026-01-15T10:00:00+01:00", "local"),
        ],
    )
    def test_utc_storage(self, conn: sqlite3.Connection, cursor: str, legacy: LegacyFormat) -> None:
        _set_flag(conn, "utc")
        assert normalize_cursor(cursor, legacy, conn) == "2026-01-15T09:00:00.000000+00:00"


def _local_date(conn: sqlite3.Connection, value: str | None, legacy: str) -> str | None:
    row = conn.execute("SELECT app_local_date(?, ?)", (value, legacy)).fetchone()
    result: str | None = row[0]
    return result


class TestAppLocalDateSql:
    @pytest.mark.parametrize(
        ("value", "legacy", "expected"),
        [
            # Naive local: the stored wall-clock date
            ("2026-10-25T23:30:00", "local", "2026-10-25"),
            ("2026-10-25 00:10:00", "local", "2026-10-25"),
            ("2026-10-25T02:30:00.123456", "local", "2026-10-25"),
            # Naive UTC near local midnight (CET: +1, CEST: +2)
            ("2026-10-25T22:59:59", "utc", "2026-10-25"),
            ("2026-10-25T23:00:00", "utc", "2026-10-26"),
            ("2026-07-15T21:59:59.999999", "utc", "2026-07-15"),
            ("2026-07-15 22:00:00", "utc", "2026-07-16"),
            ("2026-03-28T23:00:00", "utc", "2026-03-29"),
            ("2026-03-29T22:00:00", "utc", "2026-03-30"),
            # Explicit offsets, whatever the legacy kind
            ("2026-10-25T23:00:00Z", "local", "2026-10-26"),
            ("2026-10-25T22:59:59.000000+00:00", "local", "2026-10-25"),
            ("2026-07-15T22:00:00+00:00", "utc", "2026-07-16"),
            ("2026-07-16T00:30:00+02:00", "utc", "2026-07-16"),
            ("2026-07-15T18:30:00-04:00", "local", "2026-07-16"),
            ("2026-12-31T23:00:00.000000+00:00", "utc", "2027-01-01"),
        ],
    )
    def test_every_format(
        self, conn: sqlite3.Connection, value: str, legacy: str, expected: str
    ) -> None:
        assert _local_date(conn, value, legacy) == expected

    def test_null_and_garbage_give_null(self, conn: sqlite3.Connection) -> None:
        assert _local_date(conn, None, "utc") is None
        assert _local_date(conn, "not a timestamp", "utc") is None

    def test_unknown_legacy_kind_is_an_error(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(sqlite3.OperationalError, match="user-defined function"):
            _local_date(conn, "2026-01-01T00:00:00", "Europe/Prague")

    def test_follows_app_timezone(
        self, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Config, "APP_TIMEZONE", "Pacific/Chatham")  # +13:45 in October
        assert _local_date(conn, "2026-10-25T10:15:00+00:00", "utc") == "2026-10-26"

    def test_groups_mixed_formats_by_local_day(self, conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE events (ts TEXT)")
        rows = [
            ("2026-10-25T23:30:00",),  # naive UTC -> Oct 26 00:30 CET
            ("2026-10-25T23:00:00.000000+00:00",),  # Oct 26 00:00 CET
            ("2026-10-25T22:59:59Z",),  # Oct 25 23:59:59 CET
            ("2026-10-25T00:30:00",),  # naive UTC -> Oct 25 02:30 CEST
        ]
        conn.executemany("INSERT INTO events VALUES (?)", rows)
        grouped = conn.execute(
            "SELECT app_local_date(ts, 'utc') AS day, COUNT(*) FROM events "
            "GROUP BY day ORDER BY day"
        ).fetchall()
        assert grouped == [("2026-10-25", 2), ("2026-10-26", 2)]

    def test_usable_in_an_index(self, conn: sqlite3.Connection) -> None:
        """Deterministic, so SQLite accepts it in an expression index."""
        conn.execute("CREATE TABLE events (ts TEXT)")
        conn.execute("CREATE INDEX events_day ON events (app_local_date(ts, 'utc'))")

    def test_registered_on_every_pooled_connection(self, test_database: Database) -> None:
        import threading

        results: list[str | None] = []

        def query() -> None:
            with test_database._pool.get_connection() as pooled:
                results.append(_local_date(pooled, "2026-07-15T22:00:00", "utc"))

        query()
        worker = threading.Thread(target=query)  # a new thread gets a new connection
        worker.start()
        worker.join()
        assert results == ["2026-07-16", "2026-07-16"]
