"""Tests for the embeddings storage mixin (real SQLite via test_database)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.models import Database, User


class TestEmbeddingsMixin:
    def test_upsert_and_get(self, test_database: Database, test_user: User) -> None:
        test_database.upsert_embedding(
            test_user.id, "memory", "mem-1", "gemini-embedding-001", 4, b"\x00" * 16
        )

        rows = test_database.get_embeddings(test_user.id, "memory")

        assert rows == [("mem-1", 4, b"\x00" * 16)]

    def test_upsert_replaces_existing(self, test_database: Database, test_user: User) -> None:
        test_database.upsert_embedding(
            test_user.id, "memory", "mem-1", "gemini-embedding-001", 4, b"\x00" * 16
        )
        test_database.upsert_embedding(
            test_user.id, "memory", "mem-1", "gemini-embedding-001", 4, b"\x01" * 16
        )

        rows = test_database.get_embeddings(test_user.id, "memory")

        assert len(rows) == 1
        assert rows[0][2] == b"\x01" * 16

    def test_scoped_by_user_and_kind(self, test_database: Database, test_user: User) -> None:
        test_database.upsert_embedding(
            test_user.id, "memory", "mem-1", "gemini-embedding-001", 4, b"\x00" * 16
        )
        test_database.upsert_embedding(
            test_user.id, "message", "msg-1", "gemini-embedding-001", 4, b"\x00" * 16
        )
        test_database.upsert_embedding(
            "other-user", "memory", "mem-2", "gemini-embedding-001", 4, b"\x00" * 16
        )

        assert [r[0] for r in test_database.get_embeddings(test_user.id, "memory")] == ["mem-1"]
        assert [r[0] for r in test_database.get_embeddings(test_user.id, "message")] == ["msg-1"]

    def test_delete_embedding(self, test_database: Database, test_user: User) -> None:
        test_database.upsert_embedding(
            test_user.id, "memory", "mem-1", "gemini-embedding-001", 4, b"\x00" * 16
        )

        test_database.delete_embedding("memory", "mem-1")

        assert test_database.get_embeddings(test_user.id, "memory") == []


class TestMessageEmbeddingHook:
    """add_message / update_message_content schedule background embeddings."""

    def test_add_message_schedules_embedding(
        self, test_database, test_user, test_conversation, monkeypatch
    ) -> None:
        from src.config import Config

        monkeypatch.setattr(Config, "EMBEDDINGS_ENABLED", True)
        calls: list[tuple] = []
        monkeypatch.setattr(
            test_database,
            "embed_and_store_async",
            lambda *args: calls.append(args),
        )

        message = test_database.add_message(test_conversation.id, "user", "Hello world")

        assert calls == [(test_user.id, "message", message.id, "Hello world")]

    def test_update_message_content_reembeds(
        self, test_database, test_user, test_conversation, monkeypatch
    ) -> None:
        from src.config import Config

        monkeypatch.setattr(Config, "EMBEDDINGS_ENABLED", True)
        calls: list[tuple] = []
        monkeypatch.setattr(
            test_database,
            "embed_and_store_async",
            lambda *args: calls.append(args),
        )

        message = test_database.add_message(test_conversation.id, "assistant", "placeholder")
        test_database.update_message_content(message.id, "final answer")

        assert calls[-1] == (test_user.id, "message", message.id, "final answer")

    def test_empty_content_not_embedded(
        self, test_database, test_user, test_conversation, monkeypatch
    ) -> None:
        from src.config import Config

        monkeypatch.setattr(Config, "EMBEDDINGS_ENABLED", True)
        calls: list[tuple] = []
        monkeypatch.setattr(
            test_database,
            "embed_and_store_async",
            lambda *args: calls.append(args),
        )

        test_database.add_message(test_conversation.id, "assistant", "   ")

        assert calls == []


# --- Nov 16 2026: embeddings go with their message (migration 0095) --------

import importlib.util  # noqa: E402
from types import ModuleType  # noqa: E402


def _migration() -> ModuleType:
    import yoyo

    spec = importlib.util.spec_from_file_location(
        "m0095", "migrations/0095_message_embedding_cleanup.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    original = yoyo.step
    yoyo.step = lambda *args, **kwargs: None  # type: ignore[assignment]
    try:
        spec.loader.exec_module(module)
    finally:
        yoyo.step = original
    return module


def _embed(db: Database, user_id: str, kind: str, ref_id: str) -> None:
    db.upsert_embedding(user_id, kind, ref_id, "gemini-embedding-001", 1, b"\x00" * 4)


def _ids(db: Database, user_id: str) -> set[str]:
    return {row[0] for row in db.get_embeddings(user_id, "message")}


def _conv_with(db: Database, user: User, *texts: str) -> tuple[str, list[str]]:
    conv = db.create_conversation(user_id=user.id, title="t", model="m")
    ids = []
    for text in texts:
        msg = db.add_message(conversation_id=conv.id, role="user", content=text)
        _embed(db, user.id, "message", msg.id)
        ids.append(msg.id)
    return conv.id, ids


class TestMessageEmbeddingCleanup:
    def test_purge_removes_only_orphans(self, test_database: Database, test_user: User) -> None:
        _, (live,) = _conv_with(test_database, test_user, "live")
        trashed_conv, (trashed,) = _conv_with(test_database, test_user, "trashed")
        test_database.trash_conversation(trashed_conv, test_user.id)
        _embed(test_database, test_user.id, "message", "gone-message")
        _embed(test_database, test_user.id, "memory", "mem-1")
        with test_database._pool.get_connection() as conn:
            conn.execute(_migration().PURGE_ORPHANS_SQL)
            conn.commit()
        assert _ids(test_database, test_user.id) == {live, trashed}
        assert [r[0] for r in test_database.get_embeddings(test_user.id, "memory")] == ["mem-1"]

    def test_deleting_a_message_deletes_its_embedding(
        self, test_database: Database, test_user: User
    ) -> None:
        _, (keep, gone) = _conv_with(test_database, test_user, "a", "b")
        assert test_database.delete_message(gone, test_user.id)
        assert _ids(test_database, test_user.id) == {keep}

    def test_truncating_deletes_the_tail_embeddings(
        self, test_database: Database, test_user: User
    ) -> None:
        conv_id, (first, _second, _third) = _conv_with(test_database, test_user, "a", "b", "c")
        test_database.delete_messages_after(conv_id, test_user.id, first, inclusive=False)
        assert _ids(test_database, test_user.id) == {first}

    def test_deleting_a_conversation_deletes_its_embeddings(
        self, test_database: Database, test_user: User
    ) -> None:
        conv_id, _ = _conv_with(test_database, test_user, "a", "b")
        test_database.delete_conversation(conv_id, test_user.id)
        assert _ids(test_database, test_user.id) == set()

    def test_emptying_the_trash_deletes_its_embeddings(
        self, test_database: Database, test_user: User
    ) -> None:
        _, (live,) = _conv_with(test_database, test_user, "live")
        conv_id, _ = _conv_with(test_database, test_user, "a", "b")
        test_database.trash_conversation(conv_id, test_user.id)
        assert len(_ids(test_database, test_user.id)) == 3  # trashed ones stay until the purge
        test_database.empty_trash(test_user.id)
        assert _ids(test_database, test_user.id) == {live}


class TestMessageRowBounds:
    def test_bounds_drop_rows_outside(self, test_database: Database, test_user: User) -> None:
        from datetime import UTC, datetime

        from src.db.models.timestamps import to_db

        _, (old, new) = _conv_with(test_database, test_user, "old", "new")
        with test_database._pool.get_connection() as conn:
            conn.execute(
                "UPDATE messages SET created_at = ? WHERE id = ?",
                (to_db(datetime(2026, 11, 1, tzinfo=UTC)), old),
            )
            conn.commit()
        rows = test_database.get_message_rows_for_ids(
            test_user.id, [old, new], after=datetime(2026, 11, 5, tzinfo=UTC)
        )
        assert [r[0] for r in rows] == [new]
        rows = test_database.get_message_rows_for_ids(
            test_user.id, [old, new], before=datetime(2026, 11, 5, tzinfo=UTC)
        )
        assert [r[0] for r in rows] == [old]
