"""Migration 0072 rewrites stored timestamps as fixed-width UTC."""

import importlib.util
import sqlite3
from types import ModuleType
from zoneinfo import ZoneInfo

import pytest

PRAGUE = ZoneInfo("Europe/Prague")


@pytest.fixture(scope="module")
def m() -> ModuleType:
    """The migration module, loaded outside yoyo (step() needs its collector)."""
    import yoyo

    spec = importlib.util.spec_from_file_location("m0072", "migrations/0072_timestamps_to_utc.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    original = yoyo.step
    yoyo.step = lambda *args, **kwargs: None  # type: ignore[assignment]
    try:
        spec.loader.exec_module(module)
    finally:
        yoyo.step = original
    return module


@pytest.fixture(autouse=True)
def _prague(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config import Config

    monkeypatch.setattr(Config, "LEGACY_TIMESTAMP_TIMEZONE", "Europe/Prague")


class TestToUtc:
    def test_local_summer_and_winter(self, m: ModuleType) -> None:
        assert m.to_utc("2026-07-01T12:00:00.123456", "local") == "2026-07-01T10:00:00.123456+00:00"
        assert m.to_utc("2026-01-05 12:00:00", "local") == "2026-01-05T11:00:00.000000+00:00"

    def test_utc(self, m: ModuleType) -> None:
        assert m.to_utc("2026-10-12T08:29:31", "utc") == "2026-10-12T08:29:31.000000+00:00"

    def test_utc_since_reads_rows_before_the_cutoff_as_local(self, m: ModuleType) -> None:
        assert m.to_utc("2026-03-04T19:49:27", "utc_since") == "2026-03-04T18:49:27.000000+00:00"
        assert m.to_utc("2026-06-12T05:17:54", "utc_since") == "2026-06-12T05:17:54.000000+00:00"

    def test_an_offset_value_is_only_normalized(self, m: ModuleType) -> None:
        assert m.to_utc("2026-07-01T12:00:00+02:00", "local") == "2026-07-01T10:00:00.000000+00:00"
        fixed = "2026-07-01T10:00:00.000000+00:00"
        assert m.to_utc(fixed, "local") == fixed

    def test_empty_values_stay(self, m: ModuleType) -> None:
        assert m.to_utc(None, "local") is None
        assert m.to_utc("", "local") == ""

    @pytest.mark.parametrize(
        ("value", "kind"),
        [
            ("2026-07-01T12:00:00.123456", "local"),
            ("2026-01-05T12:00:00", "local"),
            ("2026-03-04T19:49:27.5", "utc_since"),
            ("2026-08-04T19:49:27.5", "utc_since"),
            ("2026-10-12T08:29:31", "utc"),
        ],
    )
    def test_to_legacy_is_the_inverse(self, m: ModuleType, value: str, kind: str) -> None:
        from datetime import datetime

        back = m.to_legacy(m.to_utc(value, kind), kind)
        assert datetime.fromisoformat(back) == datetime.fromisoformat(value)


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE conversations (id TEXT, user_id TEXT, is_agent INTEGER,
            created_at TEXT, updated_at TEXT, deleted_at TEXT);
        CREATE TABLE messages (id TEXT, conversation_id TEXT, created_at TEXT);
        CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL,
            updated_at TEXT NOT NULL);
        CREATE TABLE weather_cache (location TEXT, cached_at TEXT);
        CREATE TABLE sync_counter (id INTEGER PRIMARY KEY, value INTEGER);
        INSERT INTO sync_counter VALUES (1, 0);
        CREATE TRIGGER sync_change_message_update AFTER UPDATE ON messages BEGIN
            UPDATE sync_counter SET value = value + 1 WHERE id = 1;
        END;
        """
    )
    return conn


class TestConvert:
    def test_rewrites_columns_and_sets_the_flag(self, m: ModuleType) -> None:
        conn = _db()
        conn.execute(
            "INSERT INTO conversations VALUES "
            "('c1', 'u', 0, '2026-07-01T12:00:00', '2026-07-01T12:30:00', NULL)"
        )
        conn.execute(
            "INSERT INTO conversations VALUES "
            "('c2', 'u', 1, '2026-07-01T12:00:00', '2026-07-01T14:00:00', NULL)"
        )
        conn.execute("INSERT INTO weather_cache VALUES ('Praha', '2026-10-26T06:14:43')")

        m.convert(conn)

        rows = dict(conn.execute("SELECT id, created_at FROM conversations").fetchall())
        assert rows["c1"] == "2026-07-01T10:00:00.000000+00:00"
        # An agent conversation's created_at was written UTC-naive
        assert rows["c2"] == "2026-07-01T12:00:00.000000+00:00"
        assert conn.execute("SELECT deleted_at FROM conversations").fetchone()[0] is None
        assert conn.execute("SELECT count(*) FROM weather_cache").fetchone()[0] == 0
        flag = conn.execute("SELECT value FROM app_settings WHERE key = 'timestamp_storage'")
        assert flag.fetchone()[0] == "utc"

    def test_messages_are_rewritten_without_a_sync_bump_each(self, m: ModuleType) -> None:
        conn = _db()
        conn.executemany(
            "INSERT INTO messages VALUES (?, 'c1', '2026-07-01T12:00:00')",
            [("m1",), ("m2",), ("m3",)],
        )
        trigger_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'sync_change_message_update'"
        ).fetchone()[0]

        m.convert(conn)

        assert conn.execute("SELECT value FROM sync_counter").fetchone()[0] == 0
        created = {r[0] for r in conn.execute("SELECT created_at FROM messages")}
        assert created == {"2026-07-01T10:00:00.000000+00:00"}
        # The trigger is back, unchanged, and fires again
        assert (
            conn.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'sync_change_message_update'"
            ).fetchone()[0]
            == trigger_sql
        )
        conn.execute("UPDATE messages SET created_at = created_at WHERE id = 'm1'")
        assert conn.execute("SELECT value FROM sync_counter").fetchone()[0] == 1

    def test_a_second_run_changes_nothing(self, m: ModuleType) -> None:
        conn = _db()
        conn.execute("INSERT INTO messages VALUES ('m1', 'c1', '2026-01-05T12:00:00')")
        m.convert(conn)
        once = conn.execute("SELECT created_at FROM messages").fetchone()[0]
        m.convert(conn)
        assert conn.execute("SELECT created_at FROM messages").fetchone()[0] == once

    def test_revert_restores_the_legacy_values_and_drops_the_flag(self, m: ModuleType) -> None:
        conn = _db()
        conn.execute("INSERT INTO messages VALUES ('m1', 'c1', '2026-01-05T12:00:00.250000')")
        m.convert(conn)
        m.revert(conn)
        assert conn.execute("SELECT created_at FROM messages").fetchone()[0] == (
            "2026-01-05T12:00:00.250000"
        )
        assert conn.execute("SELECT count(*) FROM app_settings").fetchone()[0] == 0
