"""Migration 0086 (proposals): the table and its sync triggers roll back
cleanly, and the old kv previews are cleared on the way up."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from yoyo import get_backend, read_migrations

from src.db.models import Database
from src.db.models import base as db_base

if TYPE_CHECKING:
    from pathlib import Path

_ID = "0086_proposals"


def _migrate(path: Path, rollback: bool = False) -> None:
    backend = get_backend(f"sqlite:///{path}")
    migrations = read_migrations(str(db_base.MIGRATIONS_DIR))
    with backend.lock():
        if rollback:
            backend.rollback_migrations(
                backend.to_rollback(migrations).filter(lambda m: m.id == _ID)
            )
        else:
            backend.apply_migrations(backend.to_apply(migrations))


def test_rollback_0086(test_db_path: Path) -> None:
    Database(db_path=test_db_path).close()
    _migrate(test_db_path, rollback=True)
    conn = sqlite3.connect(test_db_path)
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()
    assert "proposals" not in names
    assert not {n for n in names if n.startswith("sync_change_proposal")}


def test_old_kv_previews_are_cleared(test_db_path: Path) -> None:
    db = Database(db_path=test_db_path)
    user = db.get_or_create_user(email="a@example.com", name="A")
    db.close()
    _migrate(test_db_path, rollback=True)
    db = Database(db_path=test_db_path, apply_migrations=False)
    for namespace in ("schedule_pending", "standing_create_pending", "standing_pending", "notes"):
        db.kv_set(user.id, namespace, "conv-1", "{}")
    db.close()

    _migrate(test_db_path)

    db = Database(db_path=test_db_path, apply_migrations=False)
    left = [
        ns
        for ns in ("schedule_pending", "standing_create_pending", "standing_pending", "notes")
        if db.kv_get(user.id, ns, "conv-1") is not None
    ]
    db.close()
    assert left == ["notes"]
