"""Migration 0085: announcement posts remember their message (so an edited
announcement revises it); existing posts are paired with the message posted
at the same moment."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from yoyo import get_backend, read_migrations

from src.db.models import Database
from src.db.models import base as db_base
from src.enums import MessageRole

if TYPE_CHECKING:
    from pathlib import Path

_ID = "0085_announcement_post_messages"


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


def test_existing_posts_are_paired_with_their_message(test_db_path: Path) -> None:
    db = Database(db_path=test_db_path)
    user = db.get_or_create_user(email="a@example.com", name="A")
    conv_id = db.whats_new_conversation_for_post(user.id, "Novinky")
    first = db.add_message(conv_id, MessageRole.ASSISTANT, "# One")
    second = db.add_message(conv_id, MessageRole.ASSISTANT, "# Two")
    db.close()
    _migrate(test_db_path, rollback=True)
    conn = sqlite3.connect(test_db_path)
    conn.row_factory = sqlite3.Row
    created = {
        r["id"]: r["created_at"] for r in conn.execute("SELECT id, created_at FROM messages")
    }
    conn.executemany(
        "INSERT INTO announcement_posts (user_id, announcement_id, posted_at) VALUES (?, ?, ?)",
        [
            (user.id, "a-one", created[first.id]),
            (user.id, "a-two", created[second.id]),
            (user.id, "a-gone", "2020-01-01T00:00:00.000000Z"),  # its chat was deleted
        ],
    )
    conn.commit()
    conn.close()

    _migrate(test_db_path)

    conn = sqlite3.connect(test_db_path)
    rows = dict(conn.execute("SELECT announcement_id, message_id FROM announcement_posts"))
    conn.close()
    assert rows == {"a-one": first.id, "a-two": second.id, "a-gone": None}


def test_rollback_0085(test_db_path: Path) -> None:
    Database(db_path=test_db_path).close()
    _migrate(test_db_path, rollback=True)
    conn = sqlite3.connect(test_db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(announcement_posts)")}
    conn.close()
    assert "message_id" not in columns
