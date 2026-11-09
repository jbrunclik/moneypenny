"""Migration 0087: only a change a device shows bumps sync; rolling back
restores 0086's bump-on-every-update trigger."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from yoyo import get_backend, read_migrations

from src.db.models import Database
from src.db.models import base as db_base

if TYPE_CHECKING:
    from pathlib import Path


def _trigger_sql(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'sync_change_proposal_update'"
        ).fetchone()
    finally:
        conn.close()
    return str(row[0])


def test_rollback_0087(test_db_path: Path) -> None:
    Database(db_path=test_db_path).close()
    assert "UPDATE OF state" in _trigger_sql(test_db_path)

    backend = get_backend(f"sqlite:///{test_db_path}")
    migrations = read_migrations(str(db_base.MIGRATIONS_DIR))
    with backend.lock():
        backend.rollback_migrations(
            backend.to_rollback(migrations).filter(lambda m: m.id == "0087_proposal_sync_on_change")
        )

    assert "UPDATE OF" not in _trigger_sql(test_db_path)
