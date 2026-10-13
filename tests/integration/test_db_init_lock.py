"""Opening the database must not depend on yoyo's migration lock when
nothing is pending (Oct 13 2026 outage: a scheduler run stranded the lock
row while a long purge held SQLite's write lock, and the next deploy's
workers crash-looped on LockTimeout)."""

from pathlib import Path

from src.db.models import Database


def _plant_stale_lock(db_path: Path) -> None:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO yoyo_lock (locked, ctime, pid) VALUES (1, '2026-10-13 16:38:12', 999999)"
    )
    conn.commit()
    conn.close()


def test_open_with_stale_lock_and_nothing_pending(test_db_path: Path) -> None:
    Database(db_path=test_db_path).close()  # migrates the fresh file
    _plant_stale_lock(test_db_path)

    db = Database(db_path=test_db_path)  # LockTimeout before the fix

    assert db.get_or_create_user("lock@example.com", "Lock").email == "lock@example.com"
    db.close()


def test_fresh_database_still_migrates(test_db_path: Path) -> None:
    db = Database(db_path=test_db_path)
    with db._pool.get_connection() as conn:
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"conversations", "_yoyo_migration"} <= tables
    db.close()
