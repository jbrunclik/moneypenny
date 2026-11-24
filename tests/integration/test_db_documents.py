"""Integration tests for saved-document (document memory) storage."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from src.db.models.documents import DocumentWriteError
from src.db.models.helpers import make_document_blob_key
from src.db.models.timestamps import to_db
from src.utils.clock import utc_now

if TYPE_CHECKING:
    from src.db.blob_store import BlobStore
    from src.db.models import Database, Document, User


def _add(db: Database, user_id: str, data: bytes = b"%PDF-1.4 lease", **kw: Any) -> Document:
    fields: dict[str, Any] = {
        "title": "Lease",
        "summary": "Flat lease, 25k CZK a month",
        "use_for": "Rent and notice questions",
        "filename": "lease.pdf",
        "mime_type": "application/pdf",
        "data": data,
        "valid_until": None,
        "source_conversation_id": "conv-1",
        "source_message_id": "msg-1",
    }
    fields.update(kw)
    return db.add_document(user_id, **fields)


def _blob_count(store: BlobStore) -> int:
    with store._pool.get_connection() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM blobs").fetchone()[0])


class TestDocumentStorage:
    def test_add_and_get_roundtrip(
        self, test_database: Database, test_blob_store: BlobStore, test_user: User
    ) -> None:
        doc = _add(test_database, test_user.id, data=b"abc123")

        got = test_database.get_document(doc.id, test_user.id)
        assert got is not None
        assert got.title == "Lease"
        assert got.size_bytes == 6
        assert got.source_conversation_id == "conv-1"
        blob = test_blob_store.get(make_document_blob_key(doc.id))
        assert blob is not None
        assert blob[0] == b"abc123"
        assert [d.id for d in test_database.list_documents(test_user.id)] == [doc.id]

    def test_get_other_users_document_is_none(
        self, test_database: Database, test_blob_store: BlobStore, test_user: User
    ) -> None:
        doc = _add(test_database, test_user.id)
        assert test_database.get_document(doc.id, "someone-else") is None

    def test_add_document_replacing_foreign_id_writes_nothing(
        self, test_database: Database, test_blob_store: BlobStore, test_user: User
    ) -> None:
        other = test_database.get_or_create_user("other@example.com", "Other")
        foreign = _add(test_database, other.id)
        blobs_before = _blob_count(test_blob_store)

        with pytest.raises(DocumentWriteError):
            _add(test_database, test_user.id, replaces=foreign.id)

        assert test_database.list_documents(test_user.id) == []
        assert _blob_count(test_blob_store) == blobs_before
        assert test_database.get_document(foreign.id, other.id) is not None

    def test_replaces_soft_deletes_old(
        self, test_database: Database, test_blob_store: BlobStore, test_user: User
    ) -> None:
        old = _add(test_database, test_user.id)
        new = _add(test_database, test_user.id, title="Lease v2", replaces=old.id)

        assert [d.id for d in test_database.list_documents(test_user.id)] == [new.id]
        assert [d.id for d in test_database.list_deleted_documents(test_user.id)] == [old.id]

    def test_update_fields_and_clear_end_date(
        self, test_database: Database, test_blob_store: BlobStore, test_user: User
    ) -> None:
        doc = _add(test_database, test_user.id, valid_until=date(2027, 1, 1))

        updated = test_database.update_document(
            doc.id, test_user.id, summary="New summary", valid_until=None
        )
        assert updated is not None
        assert updated.summary == "New summary"
        assert updated.title == "Lease"
        assert updated.valid_until is None

    def test_update_leaves_end_date_when_not_given(
        self, test_database: Database, test_blob_store: BlobStore, test_user: User
    ) -> None:
        doc = _add(test_database, test_user.id, valid_until=date(2027, 1, 1))
        updated = test_database.update_document(doc.id, test_user.id, title="Renamed")
        assert updated is not None
        assert updated.valid_until == date(2027, 1, 1)

    def test_expire_boundary(
        self, test_database: Database, test_blob_store: BlobStore, test_user: User
    ) -> None:
        doc = _add(test_database, test_user.id, valid_until=date(2026, 12, 1))

        assert not doc.expired(date(2026, 12, 1))
        assert doc.expired(date(2026, 12, 2))
        assert test_database.expire_documents(date(2026, 12, 1)) == 0
        assert test_database.expire_documents(date(2026, 12, 2)) == 1
        assert test_database.list_documents(test_user.id) == []

    def test_purge_deletes_blob(
        self, test_database: Database, test_blob_store: BlobStore, test_user: User
    ) -> None:
        doc = _add(test_database, test_user.id)
        assert test_database.delete_document(doc.id, test_user.id)
        with test_database._pool.get_connection() as conn:
            conn.execute(
                "UPDATE user_documents SET deleted_at = ? WHERE id = ?",
                (to_db(utc_now() - timedelta(days=31)), doc.id),
            )
            conn.commit()

        assert test_database.purge_deleted_documents(30) == 1
        assert test_blob_store.get(make_document_blob_key(doc.id)) is None
        assert test_database.get_document(doc.id, test_user.id) is None

    def test_purge_keeps_recent_deletes(
        self, test_database: Database, test_blob_store: BlobStore, test_user: User
    ) -> None:
        doc = _add(test_database, test_user.id)
        test_database.delete_document(doc.id, test_user.id)
        assert test_database.purge_deleted_documents(30) == 0
        assert test_blob_store.get(make_document_blob_key(doc.id)) is not None

    def test_restore_clears_past_end_date(
        self, test_database: Database, test_blob_store: BlobStore, test_user: User
    ) -> None:
        doc = _add(test_database, test_user.id, valid_until=date(2026, 1, 1))
        test_database.expire_documents(date(2026, 1, 2))

        assert test_database.restore_document(doc.id, test_user.id, date(2026, 1, 2))
        restored = test_database.get_document(doc.id, test_user.id)
        assert restored is not None
        assert restored.deleted_at is None
        assert restored.valid_until is None

    def test_usage_counts_deleted_bytes_not_entries(
        self, test_database: Database, test_blob_store: BlobStore, test_user: User
    ) -> None:
        _add(test_database, test_user.id, data=b"x" * 10)
        gone = _add(test_database, test_user.id, data=b"y" * 5)
        test_database.delete_document(gone.id, test_user.id)

        assert test_database.document_usage(test_user.id) == (1, 15)

    def test_touch_opened(
        self, test_database: Database, test_blob_store: BlobStore, test_user: User
    ) -> None:
        doc = _add(test_database, test_user.id)
        assert doc.last_opened_at is None
        test_database.touch_document_opened(doc.id)
        got = test_database.get_document(doc.id, test_user.id)
        assert got is not None
        assert got.last_opened_at is not None
