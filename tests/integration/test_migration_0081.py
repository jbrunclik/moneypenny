"""Migration 0081: a job's existing tool grant keeps its behavior - a writable
tool it already had gets the write level; rolling back strips the levels."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

from yoyo import get_backend, read_migrations

from src.db.models import Database
from src.db.models import base as db_base

if TYPE_CHECKING:
    from pathlib import Path


def _run(test_db_path: Path, action: str) -> None:
    backend = get_backend(f"sqlite:///{test_db_path}")
    migrations = read_migrations(str(db_base.MIGRATIONS_DIR))
    with backend.lock():
        if action == "rollback":
            target = backend.to_rollback(migrations).filter(lambda m: m.id >= "0081")
            assert "0081_grant_levels" in {m.id for m in target}
            backend.rollback_migrations(target)
        else:
            backend.apply_migrations(backend.to_apply(migrations))


def _grants(test_db_path: Path, job_id: str) -> list[str] | None:
    conn = sqlite3.connect(test_db_path)
    try:
        raw = conn.execute("SELECT grants FROM scheduled_items WHERE id = ?", (job_id,)).fetchone()[
            0
        ]
    finally:
        conn.close()
    return json.loads(raw) if raw is not None else None


def test_existing_grants_keep_their_behavior(test_db_path: Path) -> None:
    db = Database(db_path=test_db_path)
    user = db.get_or_create_user(email="a@example.com", name="A")
    db.close()
    _run(test_db_path, "rollback")
    conn = sqlite3.connect(test_db_path)
    try:
        conn.execute(
            """INSERT INTO conversations (id, user_id, title, model, created_at, updated_at)
               VALUES ('c1', ?, 't', 'm', '2026-11-08T10:00:00.000000+00:00',
                       '2026-11-08T10:00:00.000000+00:00')""",
            (user.id,),
        )
        for job_id, grants in (("j-list", '["todoist", "web_search"]'), ("j-all", '["*"]')):
            conn.execute(
                """INSERT INTO scheduled_items (id, user_id, conversation_id, kind, text,
                       next_run_at, status, quiet_runs, failures, created_at, grants)
                   VALUES (?, ?, 'c1', 'recurring', 'x', '2026-11-09T10:00:00.000000+00:00',
                           'active', 0, 0, '2026-11-08T10:00:00.000000+00:00', ?)""",
                (job_id, user.id, grants),
            )
        conn.commit()
    finally:
        conn.close()

    _run(test_db_path, "apply")

    assert sorted(_grants(test_db_path, "j-list") or []) == [
        "todoist",
        "todoist:write",
        "web_search",
    ]
    assert _grants(test_db_path, "j-all") == ["*"]

    _run(test_db_path, "rollback")

    assert sorted(_grants(test_db_path, "j-list") or []) == ["todoist", "web_search"]
