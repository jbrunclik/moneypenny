"""Migration 0088: run proposals; pending job_approvals copy in as cards on
their approval message, and job_approvals goes."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from yoyo import get_backend, read_migrations

from src.db.models import Database
from src.db.models import base as db_base
from src.enums import MessageRole

if TYPE_CHECKING:
    from pathlib import Path

_ID = "0088_run_proposals"


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


def test_a_pending_approval_becomes_a_card_on_its_message(test_db_path: Path) -> None:
    db = Database(db_path=test_db_path)
    user = db.get_or_create_user(email="a@example.com", name="A")
    agent = db.create_standing_chat(user.id, "Coach", schedule="0 20 * * *")
    message = db.add_message(
        agent.conversation_id or "",
        MessageRole.ASSISTANT,
        "[approval-request:ap-1]\n**Action requires approval**",
    )
    db.close()
    _migrate(test_db_path, rollback=True)
    conn = sqlite3.connect(test_db_path)
    conn.execute(
        """INSERT INTO job_approvals (id, item_id, user_id, tool_name, tool_args, description,
               status, created_at, expires_at)
           VALUES ('ap-1', ?, ?, 'todoist', '{"operation": "add_task"}', 'Add a task', 'pending',
               '2026-11-09T10:00:00.000000+00:00', '2099-01-01T00:00:00.000000+00:00')""",
        (agent.id, user.id),
    )
    conn.commit()
    conn.close()

    _migrate(test_db_path)

    db = Database(db_path=test_db_path, apply_migrations=False)
    card = db.get_proposal("ap-1", user.id)
    tables = {r[0] for r in sqlite3.connect(test_db_path).execute("SELECT name FROM sqlite_master")}
    db.close()
    assert card is not None
    assert (card.origin, card.kind, card.job_id, card.message_id, card.state) == (
        "run",
        "agent_action",
        agent.id,
        message.id,
        "pending",
    )
    assert "job_approvals" not in tables


def test_rollback_0088(test_db_path: Path) -> None:
    Database(db_path=test_db_path).close()
    _migrate(test_db_path, rollback=True)
    conn = sqlite3.connect(test_db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(proposals)")}
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()
    assert "origin" not in columns
    assert "job_approvals" in tables
