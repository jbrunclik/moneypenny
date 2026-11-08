"""Rolling back migration 0078 drops the standing-job columns and leaves light items."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from yoyo import get_backend, read_migrations

from src.db.models import Database
from src.db.models import base as db_base

if TYPE_CHECKING:
    from pathlib import Path


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_rollback_drops_standing_columns(test_db_path: Path) -> None:
    Database(db_path=test_db_path).close()

    backend = get_backend(f"sqlite:///{test_db_path}")
    migrations = read_migrations(str(db_base.MIGRATIONS_DIR))
    with backend.lock():
        target = backend.to_rollback(migrations).filter(lambda m: m.id == "0078_standing_jobs")
        assert len(target) == 1
        backend.rollback_migrations(target)

    conn = sqlite3.connect(test_db_path)
    try:
        items, costs = _columns(conn, "scheduled_items"), _columns(conn, "message_costs")
    finally:
        conn.close()
    standing = {"grants", "model", "budget_usd", "fresh_context", "timezone", "paused_reason"}
    assert not standing & items
    assert "job_id" not in costs
    assert {"text", "schedule", "next_run_at"} <= items
