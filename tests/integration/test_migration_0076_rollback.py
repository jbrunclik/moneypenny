"""Rolling back migration 0076 keeps pending reminders: they go back to the
reminders table they came from (watchers and other new kinds have no place
there and are dropped)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from yoyo import get_backend, read_migrations

from src.db.models import Database
from src.db.models import base as db_base
from src.db.models.dataclasses import ScheduledItem

if TYPE_CHECKING:
    from pathlib import Path

_DUE = datetime(2027, 1, 5, 8, 0, tzinfo=UTC)


def _item(user_id: str, conversation_id: str, kind: str, text: str) -> ScheduledItem:
    return ScheduledItem(
        id=str(uuid.uuid4()),
        user_id=user_id,
        conversation_id=conversation_id,
        kind=kind,  # type: ignore[arg-type]
        text=text,
        end_condition="a job is posted" if kind == "watcher" else None,
        schedule=None,
        interval_hours=24 if kind == "watcher" else None,
        next_run_at=_DUE,
        expires_at=None,
        status="active",
        last_result=None,
        quiet_runs=0,
        failures=0,
        created_at=_DUE - timedelta(days=1),
    )


def test_rollback_keeps_pending_reminders(test_db_path: Path) -> None:
    db = Database(db_path=test_db_path)
    user = db.get_or_create_user(email="a@example.com", name="A")
    conv = db.create_conversation(user.id)
    reminder = db.add_item(_item(user.id, conv.id, "reminder", "Call the plumber"))
    db.add_item(_item(user.id, conv.id, "watcher", "the job board"))
    db.close()

    backend = get_backend(f"sqlite:///{test_db_path}")
    migrations = read_migrations(str(db_base.MIGRATIONS_DIR))
    with backend.lock():
        target = backend.to_rollback(migrations).filter(lambda m: m.id == "0076_scheduled_items")
        backend.rollback_migrations(target)

    conn = sqlite3.connect(test_db_path)
    try:
        rows = conn.execute(
            "SELECT id, user_id, conversation_id, text, status FROM reminders"
        ).fetchall()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert rows == [(reminder.id, user.id, conv.id, "Call the plumber", "pending")]
    assert "scheduled_items" not in tables
