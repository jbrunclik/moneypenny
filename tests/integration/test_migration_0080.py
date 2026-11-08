"""Migration 0080: each agent becomes its chat's standing settings plus a
standing job with the agent's id; autonomous_agents becomes a view over them,
so every reader keeps working. Rolling back restores the agents table."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

from yoyo import get_backend, read_migrations

from src.db.models import Database
from src.db.models import base as db_base

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_NOW = "2026-11-08T10:00:00.000000+00:00"
_NEXT = "2026-11-09T06:15:00.000000+00:00"
_LATER = {"0082_job_tables"}  # migrations that change what 0080 made


def _migrations(test_db_path: Path, action: str) -> None:
    backend = get_backend(f"sqlite:///{test_db_path}")
    migrations = read_migrations(str(db_base.MIGRATIONS_DIR))
    with backend.lock():
        if action == "rollback":
            # 0082 drops the view and the backup 0080's rollback needs: it goes first
            backend.rollback_migrations(
                backend.to_rollback(migrations).filter(lambda m: m.id in _LATER)
            )
            target = backend.to_rollback(migrations).filter(
                lambda m: m.id == "0080_agents_to_standing_jobs"
            )
            assert len(target) == 1
            backend.rollback_migrations(target)
        else:
            # 0080's own result, before 0082 renames and drops it
            backend.apply_migrations(
                backend.to_apply(migrations).filter(lambda m: m.id not in _LATER)
            )


def _connect(test_db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(test_db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _seed_agents(test_db_path: Path) -> tuple[str, dict[str, str]]:
    """Users and pre-0080 agents (raw rows, as production has them)."""
    db = Database(db_path=test_db_path)
    user = db.get_or_create_user(email="a@example.com", name="A")
    db.close()
    _migrations(test_db_path, "rollback")
    agents = {
        "briefing": ("Daily Briefing", None, None, "15 7 * * *", 1, None, "daily_briefing", 1),
        "vwce": ("VWCE Watcher", "Watch VWCE", '["web_search"]', "0 18 * * 5", 1, 0.5, None, 1),
        "coach": ("Coach", "Coach my rides", None, "0 20 * * *", 0, None, None, 0),
    }
    ids: dict[str, str] = {}
    conn = sqlite3.connect(test_db_path)
    try:
        for key, (name, prompt, perms, cron, enabled, budget, stype, fresh) in agents.items():
            agent_id, conv_id = f"agent-{key}", f"conv-{key}"
            conn.execute(
                """INSERT INTO conversations (id, user_id, title, model, created_at, updated_at,
                       is_agent, agent_id) VALUES (?, ?, ?, 'm', ?, ?, 1, ?)""",
                (conv_id, user.id, f"Agent: {name}", _NOW, _NOW, agent_id),
            )
            conn.execute(
                """INSERT INTO autonomous_agents (id, user_id, conversation_id, name, description,
                       system_prompt, schedule, timezone, enabled, tool_permissions, model,
                       created_at, updated_at, next_run_at, last_viewed_at, budget_limit,
                       fresh_context, system_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'Europe/Prague', ?, ?, 'gemini-x', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    agent_id,
                    user.id,
                    conv_id,
                    name,
                    f"{name} desc",
                    prompt,
                    cron,
                    enabled,
                    perms,
                    _NOW,
                    _NOW,
                    _NEXT if enabled else None,
                    _NOW,
                    budget,
                    fresh,
                    stype,
                ),
            )
            ids[key] = agent_id
        conn.commit()
    finally:
        conn.close()
    _migrations(test_db_path, "apply")
    return user.id, ids


def _job(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM scheduled_items WHERE id = ?", (job_id,)).fetchone()
    assert row is not None
    return row


def test_each_agent_becomes_a_job_with_the_same_id(test_db_path: Path) -> None:
    user_id, ids = _seed_agents(test_db_path)

    for conn in _connect(test_db_path):
        job = _job(conn, ids["vwce"])
        assert (job["user_id"], job["conversation_id"], job["kind"]) == (
            user_id,
            "conv-vwce",
            "recurring",
        )
        assert (job["schedule"], job["timezone"], job["next_run_at"]) == (
            "0 18 * * 5",
            "Europe/Prague",
            _NEXT,
        )
        assert json.loads(job["grants"]) == ["web_search"]
        assert (job["model"], job["budget_usd"], job["status"]) == ("gemini-x", 0.5, "active")
        conv = conn.execute("SELECT * FROM conversations WHERE id = 'conv-vwce'").fetchone()
        assert (conv["standing_name"], conv["standing_instructions"]) == (
            "VWCE Watcher",
            "Watch VWCE",
        )
        assert (conv["standing_description"], conv["standing_viewed_at"]) == (
            "VWCE Watcher desc",
            _NOW,
        )
        assert conv["agent_id"] == ids["vwce"]


def test_unrestricted_agent_gets_all_grant(test_db_path: Path) -> None:
    _, ids = _seed_agents(test_db_path)

    for conn in _connect(test_db_path):
        assert json.loads(_job(conn, ids["briefing"])["grants"]) == ["*"]


def test_disabled_agent_job_is_paused(test_db_path: Path) -> None:
    _, ids = _seed_agents(test_db_path)

    for conn in _connect(test_db_path):
        job = _job(conn, ids["coach"])
        assert (job["status"], job["paused_reason"], job["fresh_context"]) == (
            "paused",
            "disabled",
            0,
        )


def test_briefing_job_keeps_stock_prompt(test_db_path: Path) -> None:
    _seed_agents(test_db_path)

    for conn in _connect(test_db_path):
        conv = conn.execute("SELECT * FROM conversations WHERE id = 'conv-briefing'").fetchone()
        assert (conv["standing_instructions"], conv["standing_type"]) == (None, "daily_briefing")


def test_old_rows_no_longer_scheduled(test_db_path: Path) -> None:
    _seed_agents(test_db_path)

    for conn in _connect(test_db_path):
        kinds = dict(
            conn.execute(
                "SELECT name, type FROM sqlite_master WHERE name LIKE '%autonomous_agents%'"
            ).fetchall()
        )
        assert kinds["autonomous_agents"] == "view"


def test_rollback_restores_agents(test_db_path: Path) -> None:
    _, ids = _seed_agents(test_db_path)

    _migrations(test_db_path, "rollback")

    for conn in _connect(test_db_path):
        table = conn.execute(
            "SELECT type FROM sqlite_master WHERE name = 'autonomous_agents'"
        ).fetchone()
        assert table["type"] == "table"
        names = {r["name"] for r in conn.execute("SELECT name FROM autonomous_agents")}
        assert names == {"Daily Briefing", "VWCE Watcher", "Coach"}
        jobs = conn.execute(
            "SELECT COUNT(*) FROM scheduled_items WHERE id IN (?, ?, ?)", tuple(ids.values())
        ).fetchone()[0]
        assert jobs == 0
        conv = conn.execute(
            "SELECT standing_name FROM conversations WHERE id = 'conv-vwce'"
        ).fetchone()
        assert conv["standing_name"] is None


def test_rollback_carries_agents_created_or_edited_after_the_migration(
    test_db_path: Path,
) -> None:
    user_id, ids = _seed_agents(test_db_path)
    db = Database(db_path=test_db_path)
    new = db.create_standing_chat(user_id, "Trip Planner", "Plan Rome", schedule="0 9 * * 1")
    db.update_standing_chat(ids["vwce"], user_id, instructions="Watch VWCE daily")
    db.delete_standing_chat(ids["coach"], user_id)
    db.close()

    _migrations(test_db_path, "rollback")

    for conn in _connect(test_db_path):
        rows = {r["id"]: r for r in conn.execute("SELECT * FROM autonomous_agents")}
        assert set(rows) == {ids["briefing"], ids["vwce"], new.id}  # the deleted one stays gone
        assert rows[new.id]["system_prompt"] == "Plan Rome"
        assert rows[ids["vwce"]]["system_prompt"] == "Watch VWCE daily"
        jobs = conn.execute(
            "SELECT COUNT(*) FROM scheduled_items WHERE grants IS NOT NULL"
        ).fetchone()
        assert jobs[0] == 0
        left = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE standing_name IS NOT NULL"
        ).fetchone()
        assert left[0] == 0
