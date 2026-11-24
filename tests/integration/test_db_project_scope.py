"""The scope rule: personal queries never see project rows, and project rows
are reached only through membership (projects design, Nov 2026)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

import pytest

from src.config import Config
from src.db.models.memory import MemoryLimitError, MemoryWrite, MemoryWriteConflictError
from src.utils.clock import local_today

if TYPE_CHECKING:
    from src.db.blob_store import BlobStore
    from src.db.models import Database, Document, Memory, Project, User


@pytest.fixture
def other_user(test_database: Database) -> User:
    return test_database.get_or_create_user(email="jana@example.com", name="Jana")


@pytest.fixture
def project(test_database: Database, test_user: User) -> Project:
    return test_database.create_project(test_user.id, "Home")


def _add_project_memory(
    db: Database, user_id: str, project_id: str, content: str = "Garage has 3-phase power"
) -> Memory:
    [memory_id] = db.apply_memory_batch(
        user_id,
        None,
        [MemoryWrite(action="add", content=content, category="fact", project_id=project_id)],
        project_id=project_id,
    )
    assert memory_id is not None
    memory = db.get_memory_in_scope(memory_id, user_id, project_id)
    assert memory is not None
    return memory


def _add_document(db: Database, user_id: str, project_id: str | None, **kw: Any) -> Document:
    fields: dict[str, Any] = {
        "title": "Wallbox quote",
        "summary": "11 kW install, 32 A",
        "use_for": "Wallbox questions",
        "filename": "quote.pdf",
        "mime_type": "application/pdf",
        "data": b"%PDF-1.4 quote",
        "valid_until": None,
        "source_conversation_id": "conv-1",
        "source_message_id": "msg-1",
        "project_id": project_id,
    }
    fields.update(kw)
    return db.add_document(user_id, **fields)


class TestPersonalScope:
    @pytest.mark.parametrize(
        "query",
        ["list_memories", "list_deleted_memories", "get_memory_count"],
    )
    def test_personal_memory_queries_ignore_project_rows(
        self, test_database: Database, test_user: User, project: Project, query: str
    ) -> None:
        live = _add_project_memory(test_database, test_user.id, project.id, "Live project fact")
        gone = _add_project_memory(test_database, test_user.id, project.id, "Deleted project fact")
        assert test_database.delete_memory(gone.id, test_user.id)
        personal = test_database.add_memory(test_user.id, "Likes tea")

        result = getattr(test_database, query)(test_user.id)

        if query == "get_memory_count":
            assert result == 1
        else:
            ids = {m.id for m in result}
            assert live.id not in ids
            assert gone.id not in ids
            if query == "list_memories":
                assert ids == {personal.id}

    def test_users_with_memory_counts_personal_only(
        self, test_database: Database, test_user: User, project: Project
    ) -> None:
        _add_project_memory(test_database, test_user.id, project.id)
        counts = {u.id: n for u, n in test_database.get_users_with_memory_counts(min_memories=0)}
        assert counts[test_user.id] == 0

    @pytest.mark.parametrize("query", ["list_documents", "list_deleted_documents"])
    def test_personal_document_lists_ignore_project_rows(
        self,
        test_database: Database,
        test_blob_store: BlobStore,
        test_user: User,
        project: Project,
        query: str,
    ) -> None:
        project_doc = _add_document(test_database, test_user.id, project.id)
        deleted_doc = _add_document(test_database, test_user.id, project.id, title="Old")
        assert test_database.delete_document(deleted_doc.id, test_user.id)
        personal = _add_document(test_database, test_user.id, None, title="Lease")

        ids = {d.id for d in getattr(test_database, query)(test_user.id)}

        assert project_doc.id not in ids
        assert deleted_doc.id not in ids
        if query == "list_documents":
            assert ids == {personal.id}

    def test_document_bytes_count_across_scopes(
        self, test_database: Database, test_blob_store: BlobStore, test_user: User, project: Project
    ) -> None:
        _add_document(test_database, test_user.id, project.id, data=b"12345")
        _add_document(test_database, test_user.id, None, data=b"123")

        count, used = test_database.document_usage(test_user.id, local_today())

        assert count == 1
        assert used == 8

    def test_project_document_cap_per_project(
        self,
        test_database: Database,
        test_blob_store: BlobStore,
        test_user: User,
        project: Project,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from src.db.models.documents import DocumentLimits, DocumentWriteError

        monkeypatch.setattr(Config, "PROJECT_DOCUMENTS_MAX_ENTRIES", 1)
        limits = DocumentLimits(max_entries=50, max_bytes=10**9, today=date.today())
        _add_document(test_database, test_user.id, project.id, limits=limits)
        with pytest.raises(DocumentWriteError):
            _add_document(test_database, test_user.id, project.id, limits=limits, title="Two")
        # the personal library is not affected by the project's cap
        _add_document(test_database, test_user.id, None, limits=limits, title="Mine")

    def test_instructions_turns_skip_project_chats(
        self, test_database: Database, test_user: User, project: Project
    ) -> None:
        from src.enums import MessageRole

        plain = test_database.create_conversation(test_user.id, "Plain")
        filed = test_database.create_conversation(test_user.id, "Filed")
        test_database.set_conversation_project(filed.id, test_user.id, project.id)
        for conv, text in ((plain, "plain chat turn"), (filed, "project chat turn")):
            test_database.add_message(conv.id, MessageRole.USER, text)
            test_database.add_message(conv.id, MessageRole.ASSISTANT, "ok")

        texts = [
            text for _at, text, _reply in test_database.recent_ordinary_user_turns(test_user.id, 10)
        ]

        assert "plain chat turn" in texts
        assert "project chat turn" not in texts

    def test_defrag_bulk_update_leaves_project_rows(
        self, test_database: Database, test_user: User, project: Project
    ) -> None:
        memory = _add_project_memory(test_database, test_user.id, project.id)
        test_database.bulk_update_memories(test_user.id, [memory.id], [], [])
        assert [m.id for m in test_database.list_project_memories(project.id)] == [memory.id]


class TestProjectScope:
    def test_member_patches_other_members_project_memory_author_unchanged(
        self, test_database: Database, test_user: User, other_user: User, project: Project
    ) -> None:
        test_database.add_project_member(project.id, test_user.id, other_user.id)
        memory = _add_project_memory(test_database, test_user.id, project.id)

        test_database.apply_memory_batch(
            other_user.id,
            None,
            [
                MemoryWrite(
                    action="patch",
                    memory_id=memory.id,
                    content="Garage has 3-phase power, 16 A breaker",
                    expected=memory.content,
                )
            ],
            project_id=project.id,
        )

        [got] = test_database.list_project_memories(project.id)
        assert got.content.endswith("16 A breaker")
        assert got.user_id == test_user.id
        assert test_database.list_memories(other_user.id) == []

    def test_patch_with_other_project_id_is_conflict(
        self, test_database: Database, test_user: User, project: Project
    ) -> None:
        other = test_database.create_project(test_user.id, "Bikes")
        memory = _add_project_memory(test_database, test_user.id, project.id)
        with pytest.raises(MemoryWriteConflictError):
            test_database.apply_memory_batch(
                test_user.id,
                None,
                [MemoryWrite(action="delete", memory_id=memory.id)],
                project_id=other.id,
            )
        with pytest.raises(MemoryWriteConflictError):
            test_database.apply_memory_batch(
                test_user.id, None, [MemoryWrite(action="delete", memory_id=memory.id)]
            )

    def test_project_memory_cap_rejects_add(
        self,
        test_database: Database,
        test_user: User,
        project: Project,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(Config, "PROJECT_MEMORY_MAX_ENTRIES", 1)
        _add_project_memory(test_database, test_user.id, project.id, "one")
        with pytest.raises(MemoryLimitError):
            _add_project_memory(test_database, test_user.id, project.id, "two")

    def test_get_memory_in_scope(
        self, test_database: Database, test_user: User, project: Project
    ) -> None:
        memory = _add_project_memory(test_database, test_user.id, project.id)
        personal = test_database.add_memory(test_user.id, "Likes tea")
        other = test_database.create_project(test_user.id, "Bikes")

        assert test_database.get_memory_in_scope(personal.id, test_user.id, project.id)
        assert test_database.get_memory_in_scope(memory.id, test_user.id, other.id) is None
        assert test_database.get_memory_in_scope(memory.id, test_user.id, None) is None
        assert test_database.get_memory(memory.id, test_user.id) is None

    def test_route_delete_allows_member_refuses_outsider(
        self, test_database: Database, test_user: User, other_user: User, project: Project
    ) -> None:
        outsider = test_database.get_or_create_user(email="kid@example.com", name="Kid")
        test_database.add_project_member(project.id, test_user.id, other_user.id)
        memory = _add_project_memory(test_database, test_user.id, project.id)

        assert not test_database.delete_memory(memory.id, outsider.id, allow_protected=True)
        assert not test_database.set_memory_protected(memory.id, outsider.id, True)
        assert test_database.set_memory_protected(memory.id, other_user.id, True)
        assert test_database.delete_memory(memory.id, other_user.id, allow_protected=True)
        assert not test_database.restore_memory(memory.id, outsider.id)
        assert test_database.restore_memory(memory.id, other_user.id)

    def test_member_reads_project_document_outsider_does_not(
        self,
        test_database: Database,
        test_blob_store: BlobStore,
        test_user: User,
        other_user: User,
        project: Project,
    ) -> None:
        doc = _add_document(test_database, test_user.id, project.id)
        assert test_database.get_visible_document(doc.id, other_user.id) is None
        test_database.add_project_member(project.id, test_user.id, other_user.id)
        assert test_database.get_visible_document(doc.id, other_user.id) is not None
        assert test_database.get_document_in_scope(doc.id, other_user.id, project.id) is not None
        assert test_database.get_document_in_scope(doc.id, other_user.id, None) is None
        assert test_database.get_document(doc.id, test_user.id) is None

    def test_embeddings_for_refs_returns_only_named_ids(
        self, test_database: Database, test_user: User, other_user: User
    ) -> None:
        for user, ref in ((test_user, "a"), (other_user, "b"), (other_user, "c")):
            test_database.upsert_embedding(user.id, "memory", ref, "m", 2, b"\x00" * 8)
        refs = {r for r, _dim, _vec in test_database.get_embeddings_for_refs("memory", {"a", "b"})}
        assert refs == {"a", "b"}
        assert test_database.get_embeddings_for_refs("memory", set()) == []
