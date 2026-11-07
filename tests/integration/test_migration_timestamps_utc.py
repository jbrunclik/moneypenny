"""Migration 0072 on the real schema: values in the legacy formats read back
as the same instants, now stored as fixed-width UTC."""

import re
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.db.models import Database
from src.db.models import base as db_base

_FIXED_UTC = r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}\+00:00$"
_FIRST_UTC_MIGRATION = 72


@pytest.fixture
def legacy_db(test_db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A database migrated up to 0071, before UTC storage."""
    migrations = tmp_path / "migrations"
    shutil.copytree(db_base.MIGRATIONS_DIR, migrations)
    for path in migrations.glob("[0-9][0-9][0-9][0-9]_*.py"):
        if int(path.name[:4]) >= _FIRST_UTC_MIGRATION:
            path.unlink()
    monkeypatch.setattr(db_base, "MIGRATIONS_DIR", migrations)
    return test_db_path


def _raw(db_path: Path, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(sql, params).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def test_legacy_rows_keep_their_instants(legacy_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(db_path=legacy_db)
    user = db.get_or_create_user(email="a@example.com", name="A")
    conv = db.create_conversation(user.id)
    # Raw: today's add_message writes columns later migrations add
    message_id = str(uuid.uuid4())
    db.close()
    _raw(
        legacy_db,
        "INSERT INTO messages (id, conversation_id, role, content, created_at)"
        " VALUES (?, ?, 'user', 'Ahoj', '2026-07-01T12:00:00')",
        (message_id, conv.id),
    )
    db = Database(db_path=legacy_db)
    memory = db.add_memory(user.id, "Likes tea")
    db.kv_set(user.id, "sports", "programs", "{}")
    db.close()

    # What the app wrote before UTC storage: local wall-clock (Europe/Prague)
    # for conversation data, UTC-naive for kv_store after Jun 10 2026
    local_summer = "2026-07-01T12:00:00.123456"  # CEST -> 10:00Z
    local_winter = "2026-01-05 12:00:00"  # CET -> 11:00Z
    for table in ("users", "conversations", "messages", "user_memories"):
        _raw(legacy_db, f"UPDATE {table} SET created_at = ?", (local_summer,))
    _raw(legacy_db, "UPDATE conversations SET updated_at = ?", (local_winter,))
    _raw(legacy_db, "UPDATE user_memories SET updated_at = ?", (local_winter,))
    _raw(legacy_db, "UPDATE kv_store SET updated_at = ?", ("2026-08-01T12:00:00",))

    monkeypatch.undo()  # back to the real migrations directory
    db = Database(db_path=legacy_db)
    summer = datetime(2026, 7, 1, 10, 0, 0, 123456, tzinfo=UTC)
    winter = datetime(2026, 1, 5, 11, tzinfo=UTC)
    assert db.get_user_by_id(user.id).created_at == summer
    migrated = db.get_conversation(conv.id, user.id)
    assert (migrated.created_at, migrated.updated_at) == (summer, winter)
    assert db.get_message_by_id(message_id).created_at == summer
    stored_memory = db.get_memory(memory.id, user.id)
    assert (stored_memory.created_at, stored_memory.updated_at) == (summer, winter)
    assert db.get_setting("timestamp_storage") is None  # 0074 drops 0072's flag
    db.close()

    assert _raw(legacy_db, "SELECT updated_at FROM kv_store")[0][0] == (
        "2026-08-01T12:00:00.000000+00:00"
    )
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


def test_drops_naive_gemini_file_cache_entries(
    legacy_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = Database(db_path=legacy_db)
    db.kv_set(
        "_system", "gemini_files", "old:0", '{"uri": "u", "expires_at": "2026-10-20T10:00:00"}'
    )
    fresh = '{"uri": "u", "expires_at": "2026-11-09T10:00:00.000000+00:00"}'
    db.kv_set("_system", "gemini_files", "new:0", fresh)
    db.close()

    monkeypatch.undo()
    db = Database(db_path=legacy_db)
    assert db.kv_get("_system", "gemini_files", "old:0") is None
    assert db.kv_get("_system", "gemini_files", "new:0") == fresh
    db.close()
