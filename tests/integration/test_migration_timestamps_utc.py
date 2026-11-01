"""Migration 0072 on the real schema: what the app wrote in the legacy formats
reads back as the same instants, now stored as fixed-width UTC."""

import re
import shutil
import sqlite3
from pathlib import Path

import pytest

from src.config import Config
from src.db.models import Database
from src.db.models import base as db_base

_FIXED_UTC = r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}\+00:00$"


@pytest.fixture
def legacy_db(test_db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A database migrated up to 0071 - the app still writes legacy values."""
    monkeypatch.setattr(Config, "LEGACY_TIMESTAMP_TIMEZONE", "Europe/Prague")
    migrations = tmp_path / "migrations"
    shutil.copytree(db_base.MIGRATIONS_DIR, migrations)
    (migrations / "0072_timestamps_to_utc.py").unlink()
    monkeypatch.setattr(db_base, "MIGRATIONS_DIR", migrations)
    return test_db_path


def _raw(db_path: Path, sql: str) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_legacy_rows_keep_their_instants(legacy_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(db_path=legacy_db)
    user = db.get_or_create_user(email="a@example.com", name="A")
    conv = db.create_conversation(user.id)
    message = db.add_message(conv.id, "user", "Ahoj")
    memory = db.add_memory(user.id, "Likes tea")
    db.kv_set(user.id, "sports", "programs", "{}")
    before = {
        "user": user.created_at,
        "conversation": db.get_conversation(conv.id, user.id).created_at,
        "message": db.get_message_by_id(message.id).created_at,
        "memory": db.get_memory(memory.id, user.id).created_at,
    }
    stored = _raw(legacy_db, "SELECT created_at FROM messages")[0][0]
    assert "+" not in str(stored)  # legacy naive
    db.close()

    monkeypatch.undo()  # back to the real migrations directory
    monkeypatch.setattr(Config, "LEGACY_TIMESTAMP_TIMEZONE", "Europe/Prague")
    db = Database(db_path=legacy_db)
    after = {
        "user": db.get_user_by_id(user.id).created_at,
        "conversation": db.get_conversation(conv.id, user.id).created_at,
        "message": db.get_message_by_id(message.id).created_at,
        "memory": db.get_memory(memory.id, user.id).created_at,
    }
    db.close()

    assert after == before
    for table, column in [
        ("users", "created_at"),
        ("conversations", "created_at"),
        ("conversations", "updated_at"),
        ("messages", "created_at"),
        ("user_memories", "updated_at"),
        ("kv_store", "updated_at"),
    ]:
        (value,) = _raw(legacy_db, f"SELECT {column} FROM {table}")[0]
        assert re.match(_FIXED_UTC, str(value)), (table, column, value)
