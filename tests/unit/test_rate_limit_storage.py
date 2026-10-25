"""Tests for the SQLite rate-limit storage shared across worker processes."""

import multiprocessing
import sqlite3
from pathlib import Path

import pytest
from limits import RateLimitItemPerMinute
from limits.errors import ConfigurationError
from limits.storage import storage_from_string
from limits.strategies import FixedWindowRateLimiter

from src.utils import rate_limit_storage
from src.utils.rate_limit_storage import SQLiteStorage


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "ratelimits.db"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """A settable clock for the storage module (index 0 is 'now')."""
    now = [1_000_000.0]
    monkeypatch.setattr(rate_limit_storage, "_now", lambda: now[0])
    return now


def _hit_many(path: str, key: str, count: int) -> None:
    storage = SQLiteStorage("sqlite://", path=path)
    for _ in range(count):
        storage.incr(key, 60)


class TestSQLiteStorage:
    def test_registered_under_sqlite_scheme(self, db_path: Path) -> None:
        storage = storage_from_string("sqlite://", path=str(db_path))

        assert isinstance(storage, SQLiteStorage)

    def test_requires_a_path(self) -> None:
        with pytest.raises(ConfigurationError):
            SQLiteStorage("sqlite://")

    def test_incr_counts_up_and_get_reads_it(self, db_path: Path) -> None:
        storage = SQLiteStorage("sqlite://", path=str(db_path))

        assert storage.incr("k", 60) == 1
        assert storage.incr("k", 60, amount=2) == 3
        assert storage.get("k") == 3
        assert storage.get("other") == 0

    def test_counter_expires_and_restarts(self, db_path: Path, clock: list[float]) -> None:
        storage = SQLiteStorage("sqlite://", path=str(db_path))
        storage.incr("k", 60)
        storage.incr("k", 60)
        assert storage.get_expiry("k") == clock[0] + 60

        clock[0] += 61

        assert storage.get("k") == 0
        assert storage.get_expiry("k") == clock[0]
        assert storage.incr("k", 60) == 1
        assert storage.get_expiry("k") == clock[0] + 60

    def test_window_keeps_its_first_expiry(self, db_path: Path, clock: list[float]) -> None:
        storage = SQLiteStorage("sqlite://", path=str(db_path))
        storage.incr("k", 60)
        start = clock[0]

        clock[0] += 30
        storage.incr("k", 60)

        assert storage.get_expiry("k") == start + 60

    def test_expired_rows_are_swept_lazily(self, db_path: Path, clock: list[float]) -> None:
        storage = SQLiteStorage("sqlite://", path=str(db_path))
        storage.incr("old", 10)

        clock[0] += rate_limit_storage._CLEANUP_INTERVAL_SECONDS + 1
        storage.incr("new", 10)

        with sqlite3.connect(db_path) as conn:
            keys = [row[0] for row in conn.execute("SELECT key FROM rate_limits")]
        assert keys == ["new"]

    def test_clear_and_reset(self, db_path: Path) -> None:
        storage = SQLiteStorage("sqlite://", path=str(db_path))
        storage.incr("a", 60)
        storage.incr("b", 60)

        storage.clear("a")
        assert storage.get("a") == 0
        assert storage.get("b") == 1

        assert storage.reset() == 1
        assert storage.get("b") == 0

    def test_uses_wal_mode(self, db_path: Path) -> None:
        SQLiteStorage("sqlite://", path=str(db_path)).incr("k", 60)

        with sqlite3.connect(db_path) as conn:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    def test_two_instances_share_counts(self, db_path: Path) -> None:
        first = SQLiteStorage("sqlite://", path=str(db_path))
        second = SQLiteStorage("sqlite://", path=str(db_path))

        first.incr("k", 60)
        second.incr("k", 60)

        assert first.get("k") == 2
        assert second.get("k") == 2

    def test_concurrent_processes_lose_no_hits(self, db_path: Path) -> None:
        # Create the schema up front so the workers race only on increments
        SQLiteStorage("sqlite://", path=str(db_path)).check()
        ctx = multiprocessing.get_context("spawn")
        workers = [ctx.Process(target=_hit_many, args=(str(db_path), "k", 50)) for _ in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=60)
            assert worker.exitcode == 0

        assert SQLiteStorage("sqlite://", path=str(db_path)).get("k") == 200

    def test_check_is_false_when_the_file_cannot_be_opened(self, tmp_path: Path) -> None:
        storage = SQLiteStorage("sqlite://", path=str(tmp_path / "missing-dir" / "x.db"))

        assert storage.check() is False

    def test_errors_raise_for_the_limiter_to_fail_open(self, tmp_path: Path) -> None:
        storage = SQLiteStorage("sqlite://", path=str(tmp_path / "missing-dir" / "x.db"))

        with pytest.raises(sqlite3.Error):
            storage.incr("k", 60)

    def test_fixed_window_strategy_enforces_the_limit(self, db_path: Path) -> None:
        limiter = FixedWindowRateLimiter(SQLiteStorage("sqlite://", path=str(db_path)))
        item = RateLimitItemPerMinute(2)

        assert limiter.hit(item, "user:1")
        assert limiter.hit(item, "user:1")
        assert not limiter.hit(item, "user:1")
        assert limiter.hit(item, "user:2")
