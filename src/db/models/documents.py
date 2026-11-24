"""Saved documents (document memory): rows in user_documents, bytes in the
blob store under doc/<id>.

Deletes are soft, like memories: an expired or replaced document sits in
Recently deleted for DOCUMENTS_SOFT_DELETE_RETENTION_DAYS before the nightly
purge removes the row and its blob.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Final

from src.db.blob_store import get_blob_store
from src.db.models.dataclasses import Document
from src.db.models.helpers import make_document_blob_key
from src.db.models.timestamps import from_db, from_db_or_none, to_db
from src.utils.clock import utc_now
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class Unset:
    """Marks an update argument the caller did not pass (None clears)."""


UNSET: Final = Unset()


class DocumentWriteError(Exception):
    """A document write the store refused; the message says why."""


@dataclass(frozen=True)
class DocumentLimits:
    """The library's caps, checked inside the write transaction. Only live
    documents whose last day has not passed count: a delete frees its space
    at once (the purge is the recovery window, not storage accounting)."""

    max_entries: int
    max_bytes: int
    today: date


_LIVE_WHERE = "user_id = ? AND deleted_at IS NULL AND (valid_until IS NULL OR valid_until >= ?)"


def _date_or_none(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class DocumentMixin:
    """Mixin providing saved-document database operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[object, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def add_document(
        self,
        user_id: str,
        *,
        title: str,
        summary: str,
        use_for: str,
        filename: str,
        mime_type: str,
        data: bytes,
        valid_until: date | None,
        source_conversation_id: str | None,
        source_message_id: str | None,
        replaces: str | None = None,
        limits: DocumentLimits | None = None,
    ) -> Document:
        """Store a document; ``replaces`` (a live document of this user) is
        soft-deleted in the same transaction, and ``limits`` are checked in it.

        Raises:
            DocumentWriteError: ``replaces`` is not a live document of this
                user, or the save would pass a limit. Nothing is written (the
                blob is removed again).
        """
        doc_id = str(uuid.uuid4())
        now = utc_now()
        blob_key = make_document_blob_key(doc_id)
        get_blob_store().save(blob_key, data, mime_type)
        try:
            with self._pool.get_connection() as conn:
                self._execute_with_timing(conn, "BEGIN IMMEDIATE")
                if replaces is not None:
                    self._retire_replaced(conn, replaces, user_id, now)
                if limits is not None:
                    self._check_limits(conn, user_id, len(data), limits)
                self._execute_with_timing(
                    conn,
                    """INSERT INTO user_documents
                       (id, user_id, title, summary, use_for, filename, mime_type,
                        size_bytes, valid_until, source_conversation_id,
                        source_message_id, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        doc_id,
                        user_id,
                        title,
                        summary,
                        use_for,
                        filename,
                        mime_type,
                        len(data),
                        valid_until.isoformat() if valid_until else None,
                        source_conversation_id,
                        source_message_id,
                        to_db(now),
                        to_db(now),
                    ),
                )
                conn.commit()
        except BaseException:
            get_blob_store().delete(blob_key)
            raise
        return Document(
            id=doc_id,
            user_id=user_id,
            title=title,
            summary=summary,
            use_for=use_for,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(data),
            created_at=now,
            updated_at=now,
            valid_until=valid_until,
            source_conversation_id=source_conversation_id,
            source_message_id=source_message_id,
        )

    def _retire_replaced(
        self, conn: sqlite3.Connection, doc_id: str, user_id: str, now: datetime
    ) -> None:
        """Soft-delete the document a new version replaces (uncommitted)."""
        cursor = self._execute_with_timing(
            conn,
            """UPDATE user_documents SET deleted_at = ?
               WHERE id = ? AND user_id = ? AND deleted_at IS NULL""",
            (to_db(now), doc_id, user_id),
        )
        if cursor.rowcount == 0:
            conn.rollback()
            raise DocumentWriteError(f"no saved document {doc_id} to replace")

    def _usage(self, conn: sqlite3.Connection, user_id: str, today: date) -> tuple[int, int]:
        row = self._execute_with_timing(
            conn,
            f"""SELECT COUNT(*) AS live, COALESCE(SUM(size_bytes), 0) AS bytes
                FROM user_documents WHERE {_LIVE_WHERE}""",
            (user_id, today.isoformat()),
        ).fetchone()
        return int(row["live"]), int(row["bytes"])

    def _check_limits(
        self, conn: sqlite3.Connection, user_id: str, size: int, limits: DocumentLimits
    ) -> None:
        """Refuse (rolling back) a save that would pass a cap (uncommitted)."""
        count, used = self._usage(conn, user_id, limits.today)
        if count + 1 > limits.max_entries or used + size > limits.max_bytes:
            conn.rollback()
            raise DocumentWriteError("the document library is full")

    def _row_to_document(self, row: sqlite3.Row) -> Document:
        return Document(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            summary=row["summary"],
            use_for=row["use_for"],
            filename=row["filename"],
            mime_type=row["mime_type"],
            size_bytes=int(row["size_bytes"]),
            created_at=from_db(row["created_at"]),
            updated_at=from_db(row["updated_at"]),
            valid_until=_date_or_none(row["valid_until"]),
            source_conversation_id=row["source_conversation_id"],
            source_message_id=row["source_message_id"],
            deleted_at=from_db_or_none(row["deleted_at"]),
            last_opened_at=from_db_or_none(row["last_opened_at"]),
            project_id=row["project_id"],
        )

    def get_document(self, document_id: str, user_id: str) -> Document | None:
        """A document of this user, live or deleted (None when not theirs)."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM user_documents WHERE id = ? AND user_id = ?",
                (document_id, user_id),
            ).fetchone()
        return self._row_to_document(row) if row else None

    def _list(self, user_id: str, deleted: bool) -> list[Document]:
        where = "deleted_at IS NOT NULL" if deleted else "deleted_at IS NULL"
        order = "deleted_at DESC" if deleted else "created_at DESC"
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                f"SELECT * FROM user_documents WHERE user_id = ? AND {where} ORDER BY {order}",
                (user_id,),
            ).fetchall()
        return [self._row_to_document(row) for row in rows]

    def list_documents(self, user_id: str) -> list[Document]:
        """Live documents, newest first (expired-but-unswept ones included;
        callers filter with ``Document.expired``)."""
        return self._list(user_id, deleted=False)

    def list_deleted_documents(self, user_id: str) -> list[Document]:
        """Soft-deleted documents still restorable, most recently deleted first."""
        return self._list(user_id, deleted=True)

    def update_document(
        self,
        document_id: str,
        user_id: str,
        *,
        title: str | None = None,
        summary: str | None = None,
        use_for: str | None = None,
        valid_until: date | Unset | None = UNSET,
    ) -> Document | None:
        """Change a live document's text fields or end date (None clears it).

        Returns:
            The updated document, or None when it is not a live one of this user
        """
        sets: list[str] = ["updated_at = ?"]
        params: list[object] = [to_db(utc_now())]
        for column, value in (("title", title), ("summary", summary), ("use_for", use_for)):
            if value is not None:
                sets.append(f"{column} = ?")
                params.append(value)
        if not isinstance(valid_until, Unset):
            sets.append("valid_until = ?")
            params.append(valid_until.isoformat() if valid_until else None)
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                f"""UPDATE user_documents SET {", ".join(sets)}
                    WHERE id = ? AND user_id = ? AND deleted_at IS NULL""",
                (*params, document_id, user_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_document(document_id, user_id)

    def delete_document(self, document_id: str, user_id: str) -> bool:
        """Soft-delete a live document."""
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE user_documents SET deleted_at = ?
                   WHERE id = ? AND user_id = ? AND deleted_at IS NULL""",
                (to_db(utc_now()), document_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def restore_document(self, document_id: str, user_id: str, today: date) -> bool:
        """Bring a deleted document back; a past end date is dropped, or the
        next sweep would delete it again."""
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE user_documents
                   SET deleted_at = NULL,
                       valid_until = CASE WHEN valid_until < ? THEN NULL ELSE valid_until END
                   WHERE id = ? AND user_id = ? AND deleted_at IS NOT NULL""",
                (today.isoformat(), document_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def document_usage(self, user_id: str, today: date) -> tuple[int, int]:
        """(documents, bytes) counting toward the caps: live ones whose last
        day has not passed."""
        with self._pool.get_connection() as conn:
            return self._usage(conn, user_id, today)

    def touch_document_opened(self, document_id: str) -> None:
        """Record that the agent opened the document (is the library used?)."""
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                "UPDATE user_documents SET last_opened_at = ? WHERE id = ?",
                (to_db(utc_now()), document_id),
            )
            conn.commit()

    def expire_documents(self, today: date) -> int:
        """Soft-delete live documents whose last day is before ``today``."""
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE user_documents SET deleted_at = ?
                   WHERE deleted_at IS NULL AND valid_until IS NOT NULL AND valid_until < ?""",
                (to_db(utc_now()), today.isoformat()),
            )
            conn.commit()
            return int(cursor.rowcount)

    def purge_deleted_documents(self, retention_days: int) -> int:
        """Hard-delete documents deleted more than ``retention_days`` ago,
        with their blobs. Returns the number purged."""
        cutoff = to_db(utc_now() - timedelta(days=retention_days))
        with self._pool.get_connection() as conn:
            ids = [
                row["id"]
                for row in self._execute_with_timing(
                    conn,
                    "SELECT id FROM user_documents WHERE deleted_at IS NOT NULL AND deleted_at < ?",
                    (cutoff,),
                ).fetchall()
            ]
            for doc_id in ids:
                self._execute_with_timing(
                    conn, "DELETE FROM user_documents WHERE id = ?", (doc_id,)
                )
            conn.commit()
        store = get_blob_store()
        for doc_id in ids:
            store.delete(make_document_blob_key(doc_id))
        return len(ids)
