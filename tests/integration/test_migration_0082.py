"""Migration 0082: the agent facade's tables and columns take job names -
runs and approvals carried into job_runs / job_approvals, conversations.job_id,
users.daily_briefing_job_id - and the autonomous_agents view and its backup
go. Rolling back restores them, and rolling back through 0080 still rebuilds
the agents table from the chats and jobs."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from yoyo import get_backend, read_migrations

from src.db.models import Database
from src.db.models import base as db_base

if TYPE_CHECKING:
    from pathlib import Path

_NOW = "2026-11-08T10:00:00.000000+00:00"
_MIGRATION = "0082_job_tables"


def _rollback_to(test_db_path: Path, migration_id: str) -> None:
    """Roll back every migration down to and including migration_id."""
    backend = get_backend(f"sqlite:///{test_db_path}")
    migrations = read_migrations(str(db_base.MIGRATIONS_DIR))
    with backend.lock():
        applied = backend.to_rollback(migrations)  # newest first
        ids = [m.id for m in applied]
        target = applied.filter(lambda m: m.id in ids[: ids.index(migration_id) + 1])
        backend.rollback_migrations(target)


def _apply(test_db_path: Path) -> None:
    backend = get_backend(f"sqlite:///{test_db_path}")
    migrations = read_migrations(str(db_base.MIGRATIONS_DIR))
    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))


def _seed(test_db_path: Path) -> str:
    """A standing chat + job with one run and one pending approval, pre-0082."""
    db = Database(db_path=test_db_path)
    user = db.get_or_create_user(email="a@example.com", name="A")
    db.close()
    _rollback_to(test_db_path, _MIGRATION)
    conn = sqlite3.connect(test_db_path)
    try:
        conn.execute(
            """INSERT INTO conversations (id, user_id, title, model, created_at, updated_at,
                   is_agent, agent_id, standing_name) VALUES ('c1', ?, 'Agent: Coach', 'm', ?, ?,
                   1, 'job1', 'Coach')""",
            (user.id, _NOW, _NOW),
        )
        conn.execute(
            """INSERT INTO scheduled_items (id, user_id, conversation_id, kind, text, schedule,
                   next_run_at, status, created_at, grants, timezone)
               VALUES ('job1', ?, 'c1', 'recurring', 'Do it', '0 20 * * *', ?, 'active', ?,
                   '["*"]', 'Europe/Prague')""",
            (user.id, _NOW, _NOW),
        )
        conn.execute(
            """INSERT INTO agent_executions (id, agent_id, status, trigger_type,
                   triggered_by_agent_id, started_at, completed_at, error_message)
               VALUES ('run1', 'job1', 'failed', 'agent', 'job0', ?, ?, 'boom')""",
            (_NOW, _NOW),
        )
        conn.execute(
            """INSERT INTO agent_approval_requests (id, agent_id, user_id, tool_name, tool_args,
                   description, status, created_at, expires_at)
               VALUES ('ap1', 'job1', ?, 'todoist', '{"a": 1}', 'Add a task', 'pending', ?, ?)""",
            (user.id, _NOW, _NOW),
        )
        conn.execute("UPDATE users SET daily_briefing_agent_id = 'job1' WHERE id = ?", (user.id,))
        conn.commit()
    finally:
        conn.close()
    _apply(test_db_path)
    return user.id


def _schema(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT name, type FROM sqlite_master").fetchall())


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_migration_0082_carries_runs_and_approvals(test_db_path: Path) -> None:
    user_id = _seed(test_db_path)

    conn = sqlite3.connect(test_db_path)
    try:
        run = conn.execute("SELECT * FROM job_runs").fetchall()
        approval = conn.execute(
            "SELECT id, item_id, user_id, tool_name, tool_args, status FROM job_approvals"
        ).fetchall()
        assert run == [("run1", "job1", "failed", "agent", "job0", _NOW, _NOW, "boom")]
        assert approval == [("ap1", "job1", user_id, "todoist", '{"a": 1}', "pending")]
        assert conn.execute("SELECT job_id FROM conversations WHERE id = 'c1'").fetchone() == (
            "job1",
        )
        assert conn.execute(
            "SELECT daily_briefing_job_id FROM users WHERE id = ?", (user_id,)
        ).fetchone() == ("job1",)
        schema = _schema(conn)
        for gone in (
            "autonomous_agents",
            "_autonomous_agents_0080",
            "agent_executions",
            "agent_approval_requests",
        ):
            assert gone not in schema
        assert "agent_id" not in _columns(conn, "conversations")
    finally:
        conn.close()


def test_rollback_0082(test_db_path: Path) -> None:
    user_id = _seed(test_db_path)
    _rollback_to(test_db_path, _MIGRATION)

    conn = sqlite3.connect(test_db_path)
    try:
        schema = _schema(conn)
        assert schema["autonomous_agents"] == "view"
        assert schema["_autonomous_agents_0080"] == "table"
        assert "job_runs" not in schema and "job_approvals" not in schema
        assert conn.execute(
            "SELECT id, agent_id, triggered_by_agent_id FROM agent_executions"
        ).fetchall() == [("run1", "job1", "job0")]
        assert conn.execute("SELECT id, agent_id FROM agent_approval_requests").fetchall() == [
            ("ap1", "job1")
        ]
        assert conn.execute(
            "SELECT daily_briefing_agent_id FROM users WHERE id = ?", (user_id,)
        ).fetchone() == ("job1",)
        # The view reads the agent again, with its last run
        assert conn.execute("SELECT id, name, last_run_at FROM autonomous_agents").fetchall() == [
            ("job1", "Coach", _NOW)
        ]
    finally:
        conn.close()


def test_rollback_through_0080_rebuilds_the_agents(test_db_path: Path) -> None:
    _seed(test_db_path)
    _rollback_to(test_db_path, "0080_agents_to_standing_jobs")

    conn = sqlite3.connect(test_db_path)
    try:
        assert _schema(conn)["autonomous_agents"] == "table"
        assert conn.execute(
            "SELECT id, name, conversation_id, schedule FROM autonomous_agents"
        ).fetchall() == [("job1", "Coach", "c1", "0 20 * * *")]
        assert conn.execute("SELECT agent_id FROM agent_executions").fetchall() == [("job1",)]
    finally:
        conn.close()
