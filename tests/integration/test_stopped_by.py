"""Why a turn stopped (turn budgets): the reason reaches the reply, its cost
row, and the history's Continue - also after a reload; migration 0084 keeps
old round-capped replies' Continue."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from yoyo import get_backend, read_migrations

from src.db.models import Database
from src.db.models import base as db_base

if TYPE_CHECKING:
    from pathlib import Path

    from flask.testing import FlaskClient

    from src.db.models import Conversation


def test_stopped_by_reaches_the_reply_and_history(
    client: FlaskClient,
    auth_headers: dict[str, str],
    test_conversation: Conversation,
    test_database: Database,
) -> None:
    with patch("src.api.helpers.chat_turn.ChatAgent") as agent_class:
        agent = MagicMock()
        agent.chat_batch.return_value = (
            "What I found so far.",
            [],
            {"input_tokens": 150, "output_tokens": 100, "tool_rounds": 3, "stopped_by": "cost"},
            [],
        )
        agent_class.return_value = agent
        reply = client.post(
            f"/api/conversations/{test_conversation.id}/chat/batch",
            headers=auth_headers,
            json={"message": "Compare everything"},
        )
    listed = client.get(f"/api/conversations/{test_conversation.id}", headers=auth_headers)

    assert json.loads(reply.data)["stopped_early"] is True
    assert json.loads(listed.data)["messages"][-1]["stopped_early"] is True
    with test_database._pool.get_connection() as conn:
        row = conn.execute("SELECT stopped_by FROM message_costs").fetchone()
    assert row["stopped_by"] == "cost"


def _migrate(path: Path, rollback: bool = False) -> None:
    backend = get_backend(f"sqlite:///{path}")
    migrations = read_migrations(str(db_base.MIGRATIONS_DIR))
    with backend.lock():
        if rollback:
            backend.rollback_migrations(
                backend.to_rollback(migrations).filter(
                    lambda m: m.id == "0084_message_costs_stopped_by"
                )
            )
        else:
            backend.apply_migrations(backend.to_apply(migrations))


def _cost_row(conn: sqlite3.Connection, message_id: str, rounds: int) -> None:
    conn.execute(
        """INSERT INTO message_costs (id, message_id, conversation_id, user_id, model,
               input_tokens, output_tokens, cost_usd, created_at, tool_rounds)
           VALUES (?, ?, 'c', 'u', 'm', 1, 1, 0.0, 'x', ?)""",
        (f"cost-{message_id}", message_id, rounds),
    )


def test_migration_backfills_old_capped_turns(test_db_path: Path) -> None:
    Database(db_path=test_db_path).close()
    _migrate(test_db_path, rollback=True)
    conn = sqlite3.connect(test_db_path)
    _cost_row(conn, "capped", 6)
    _cost_row(conn, "short", 2)
    conn.commit()
    conn.close()

    _migrate(test_db_path)

    conn = sqlite3.connect(test_db_path)
    rows = dict(conn.execute("SELECT message_id, stopped_by FROM message_costs").fetchall())
    conn.close()
    assert rows == {"capped": "rounds", "short": None}


def test_rollback_0084(test_db_path: Path) -> None:
    Database(db_path=test_db_path).close()
    _migrate(test_db_path, rollback=True)
    conn = sqlite3.connect(test_db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(message_costs)")}
    conn.close()
    assert "stopped_by" not in columns
