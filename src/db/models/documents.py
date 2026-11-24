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

from src.config import Config
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


_LIVE_WHERE = "deleted_at IS NULL AND (valid_until IS NULL OR valid_until >= ?)"
_PERSONAL_SQL = "user_id = ? AND project_id IS NULL"
# A document a chat turn may use: personal, or of the chat's own project
_IN_SCOPE_SQL = "((user_id = ? AND project_id IS NULL) OR project_id = ?)"
# A document the user may see in the app: personal, or of a live project
# they are a member of
_VISIBLE_SQL = """((user_id = ? AND project_id IS NULL) OR project_id IN (
    SELECT pm.project_id FROM project_members pm JOIN projects p ON p.id = pm.project_id
    WHERE pm.user_id = ? AND p.deleted_at IS NULL))"""


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
        project_id: str | None = None,
    ) -> Document:
        """Store a document; ``replaces`` (a live document of this user, or of
        ``project_id`` - any member's) is soft-deleted in the same transaction,
        and ``limits`` are checked in it. With ``project_id`` the entry cap is
        the project's (PROJECT_DOCUMENTS_MAX_ENTRIES); bytes always count
        toward the author.

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
                    self._retire_replaced(conn, replaces, user_id, now, project_id)
                if limits is not None:
                    self._check_limits(conn, user_id, len(data), limits, project_id)
                self._execute_with_timing(
                    conn,
                    """INSERT INTO user_documents
                       (id, user_id, title, summary, use_for, filename, mime_type,
                        size_bytes, valid_until, source_conversation_id,
                        source_message_id, created_at, updated_at, project_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                        project_id,
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
            project_id=project_id,
        )

    def _retire_replaced(
        self,
        conn: sqlite3.Connection,
        doc_id: str,
        user_id: str,
        now: datetime,
        project_id: str | None,
    ) -> None:
        """Soft-delete the document a new version replaces (uncommitted)."""
        cursor = self._execute_with_timing(
            conn,
            f"""UPDATE user_documents SET deleted_at = ?
               WHERE id = ? AND {_IN_SCOPE_SQL} AND deleted_at IS NULL""",
            (to_db(now), doc_id, user_id, project_id),
        )
        if cursor.rowcount == 0:
            conn.rollback()
            raise DocumentWriteError(f"no saved document {doc_id} to replace")

    def _usage(self, conn: sqlite3.Connection, user_id: str, today: date) -> tuple[int, int]:
        """(personal live documents, bytes the user authored in any scope)."""
        row = self._execute_with_timing(
            conn,
            f"""SELECT COALESCE(SUM(project_id IS NULL), 0) AS live,
                       COALESCE(SUM(size_bytes), 0) AS bytes
                FROM user_documents WHERE user_id = ? AND {_LIVE_WHERE}""",
            (user_id, today.isoformat()),
        ).fetchone()
        return int(row["live"]), int(row["bytes"])

    def _project_count(self, conn: sqlite3.Connection, project_id: str, today: date) -> int:
        row = self._execute_with_timing(
            conn,
            f"SELECT COUNT(*) FROM user_documents WHERE project_id = ? AND {_LIVE_WHERE}",
            (project_id, today.isoformat()),
        ).fetchone()
        return int(row[0])

    def _check_limits(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        size: int,
        limits: DocumentLimits,
        project_id: str | None = None,
    ) -> None:
        """Refuse (rolling back) a save that would pass a cap (uncommitted)."""
        count, used = self._usage(conn, user_id, limits.today)
        if project_id is not None:
            count = self._project_count(conn, project_id, limits.today)
            max_entries = Config.PROJECT_DOCUMENTS_MAX_ENTRIES
        else:
            max_entries = limits.max_entries
        if count + 1 > max_entries or used + size > limits.max_bytes:
            conn.rollback()
            raise DocumentWriteError(
                "the project's documents are full"
                if project_id is not None and count + 1 > max_entries
                else "the document library is full"
            )

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
        """A personal document of this user, live or deleted (None when not theirs)."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                f"SELECT * FROM user_documents WHERE id = ? AND {_PERSONAL_SQL}",
                (document_id, user_id),
            ).fetchone()
        return self._row_to_document(row) if row else None

    def get_document_in_scope(
        self, document_id: str, user_id: str, project_id: str | None
    ) -> Document | None:
        """A document a chat turn may use (live or deleted): personal, or of
        ``project_id`` (the chat's project; membership checked by the caller)."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                f"SELECT * FROM user_documents WHERE id = ? AND {_IN_SCOPE_SQL}",
                (document_id, user_id, project_id),
            ).fetchone()
        return self._row_to_document(row) if row else None

    def get_visible_document(self, document_id: str, user_id: str) -> Document | None:
        """A document the user may see in the app (live or deleted): personal,
        or of a live project they are a member of."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                f"SELECT * FROM user_documents WHERE id = ? AND {_VISIBLE_SQL}",
                (document_id, user_id, user_id),
            ).fetchone()
        return self._row_to_document(row) if row else None

    def list_project_documents(self, project_id: str) -> list[Document]:
        """A project's live documents (every member's), newest first."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM user_documents WHERE project_id = ? AND deleted_at IS NULL
                   ORDER BY created_at DESC""",
                (project_id,),
            ).fetchall()
        return [self._row_to_document(row) for row in rows]

    def _list(self, user_id: str, deleted: bool) -> list[Document]:
        where = "deleted_at IS NOT NULL" if deleted else "deleted_at IS NULL"
        order = "deleted_at DESC" if deleted else "created_at DESC"
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                f"SELECT * FROM user_documents WHERE {_PERSONAL_SQL} AND {where} ORDER BY {order}",
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
        project_id: str | None = None,
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
                    WHERE id = ? AND {_IN_SCOPE_SQL} AND deleted_at IS NULL""",
                (*params, document_id, user_id, project_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_document_in_scope(document_id, user_id, project_id)

    def delete_document(self, document_id: str, user_id: str) -> bool:
        """Soft-delete a live document the user may see (personal, or of a
        project they are in)."""
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                f"""UPDATE user_documents SET deleted_at = ?
                   WHERE id = ? AND {_VISIBLE_SQL} AND deleted_at IS NULL""",
                (to_db(utc_now()), document_id, user_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def restore_document(self, document_id: str, user_id: str, today: date) -> bool:
        """Bring a deleted document back; a past end date is dropped, or the
        next sweep would delete it again."""
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                f"""UPDATE user_documents
                   SET deleted_at = NULL,
                       valid_until = CASE WHEN valid_until < ? THEN NULL ELSE valid_until END
                   WHERE id = ? AND {_VISIBLE_SQL} AND deleted_at IS NOT NULL""",
                (today.isoformat(), document_id, user_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def document_usage(self, user_id: str, today: date) -> tuple[int, int]:
        """(personal documents, bytes of everything the user authored)
        counting toward the caps: live ones whose last day has not passed."""
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
