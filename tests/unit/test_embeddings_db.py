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
