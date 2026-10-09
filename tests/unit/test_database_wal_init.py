"""A new database is switched to WAL once, at init.

The pool also sets WAL on every new connection; on a fresh rollback-journal
file two connections doing that at the same moment make one fail at once
with "database is locked" (the busy timeout does not cover the switch). A
background thread from an earlier test opening the file alongside the test's
own first connection hit exactly that in CI.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from src.db.models import Database


def test_init_leaves_a_new_database_in_wal_mode(tmp_path: Path) -> None:
    path = tmp_path / "fresh.db"
    database = Database(db_path=path)
    try:
        # Read the mode straight from the file, before any pool connection
        conn = sqlite3.connect(path)
        try:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        finally:
            conn.close()
    finally:
        database.close()


def test_concurrent_first_connections_do_not_lock(tmp_path: Path) -> None:
    errors: list[BaseException] = []
    for i in range(20):
        database = Database(db_path=tmp_path / f"race-{i}.db")
        barrier = threading.Barrier(2)

        def first_query(db: Database = database, b: threading.Barrier = barrier) -> None:
            b.wait()
            try:
                with db._pool.get_connection() as conn:
                    conn.execute("SELECT 1").fetchone()
            except sqlite3.OperationalError as e:  # "database is locked"
                errors.append(e)

        threads = [threading.Thread(target=first_query) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        database.close()
    assert errors == []
