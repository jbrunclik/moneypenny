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
        assert test_database.count_embeddings(test_user.id, "memory") == 1
        assert test_database.count_embeddings(test_user.id, "message") == 1

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
            "src.utils.embeddings.embed_and_store_async",
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
            "src.utils.embeddings.embed_and_store_async",
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
            "src.utils.embeddings.embed_and_store_async",
            lambda *args: calls.append(args),
        )

        test_database.add_message(test_conversation.id, "assistant", "   ")

        assert calls == []
