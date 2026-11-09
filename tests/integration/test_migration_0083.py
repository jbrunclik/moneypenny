"""Migration 0083 (What's new): the chat marker and the post record apply
and roll back cleanly."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from yoyo import get_backend, read_migrations

from src.db.models import Database
from src.db.models import base as db_base

if TYPE_CHECKING:
    from pathlib import Path


def test_rollback_0083(test_db_path: Path) -> None:
    Database(db_path=test_db_path).close()
    backend = get_backend(f"sqlite:///{test_db_path}")
    migrations = read_migrations(str(db_base.MIGRATIONS_DIR))
    with backend.lock():
        backend.rollback_migrations(
            backend.to_rollback(migrations).filter(lambda m: m.id == "0083_whats_new")
        )

    conn = sqlite3.connect(test_db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(conversations)")}
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    finally:
        conn.close()
    assert "is_whats_new" not in columns
    assert "announcement_posts" not in tables
