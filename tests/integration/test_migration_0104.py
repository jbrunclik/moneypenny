"""Migration 0104: projects, their members, and project_id on chats,
memories and saved documents."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from yoyo import get_backend, read_migrations

from src.db.models import Database
from src.db.models import base as db_base

if TYPE_CHECKING:
    from pathlib import Path

_ID = "0104_projects"
_SCOPED_TABLES = ("conversations", "user_memories", "user_documents")


def _rollback(path: Path) -> None:
    backend = get_backend(f"sqlite:///{path}")
    migrations = read_migrations(str(db_base.MIGRATIONS_DIR))
    with backend.lock():
        backend.rollback_migrations(backend.to_rollback(migrations).filter(lambda m: m.id == _ID))


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_0104_applies_and_rolls_back(test_db_path: Path) -> None:
    Database(db_path=test_db_path).close()
    conn = sqlite3.connect(test_db_path)
    try:
        assert {"projects", "project_members"} <= _tables(conn)
        assert {"id", "owner_id", "name", "instructions", "deleted_at"} <= _columns(
            conn, "projects"
        )
        for table in _SCOPED_TABLES:
            assert "project_id" in _columns(conn, table)
    finally:
        conn.close()

    _rollback(test_db_path)

    conn = sqlite3.connect(test_db_path)
    try:
        assert not {"projects", "project_members"} & _tables(conn)
        for table in _SCOPED_TABLES:
            assert "project_id" not in _columns(conn, table)
    finally:
        conn.close()
