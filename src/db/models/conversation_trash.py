"""Conversation trash database operations mixin.

Deleting a chat from the UI moves it to the trash (deleted_at set) instead
of destroying it. It stays restorable until the daily cleanup sweep purges
it after TRASH_RETENTION_DAYS. The real deletion (rows, then blobs) is
ConversationMixin.delete_conversation.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.db.models.conversation_rows import page_rows, row_to_conversation_summary
from src.db.models.dataclasses import Conversation
from src.db.models.helpers import delete_messages_blobs, parse_cursor
from src.db.models.timestamps import normalize_cursor, to_db
from src.utils.clock import utc_now
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)

_TRASH_LIST_SELECT = """SELECT c.*,
                          COUNT(m.id) as message_count,
                          (SELECT m2.content FROM messages m2
                           WHERE m2.conversation_id = c.id
                           ORDER BY m2.created_at DESC, m2.id DESC LIMIT 1) as last_message
                   FROM conversations c
                   LEFT JOIN messages m ON m.conversation_id = c.id
                   WHERE c.user_id = ? AND c.deleted_at IS NOT NULL"""

# Rows the chat list shows and bulk delete may trash: regular, live chats.
# Agent / planner / sports / language chats are owned by their feature.
_TRASHABLE_WHERE = """user_id = ? AND deleted_at IS NULL
    AND (is_agent = 0 OR is_agent IS NULL)
    AND (is_planning = 0 OR is_planning IS NULL)
    AND (is_sports = 0 OR is_sports IS NULL)
    AND (is_language = 0 OR is_language IS NULL)"""


# Trash bumps updated_at (the trash list sorts by it) and remembers the old
# value once; restore puts it back. A re-trash keeps the first deleted_at and
# the original updated_at. Params: (deleted_at, updated_at).
_TRASH_SET = """trashed_updated_at = CASE WHEN deleted_at IS NULL
                                       THEN updated_at ELSE trashed_updated_at END,
    deleted_at = COALESCE(deleted_at, ?), updated_at = ?"""
_RESTORE_SET = """updated_at = CASE WHEN deleted_at IS NULL THEN updated_at
                     ELSE COALESCE(trashed_updated_at, updated_at) END,
    deleted_at = NULL, trashed_updated_at = NULL"""


# Trashed conversations hard-deleted per transaction when emptying the trash
# or purging. One commit per chat took ~0.1 s each (a 1000-chat trash ran for
# minutes, Oct 13 2026); 25 per chunk keeps each write-lock hold short so
# chat saves interleave (1000 chats: ~6 s in all since the search index
# deletes by key, migration 0067).
_PURGE_CHUNK = 25


def _placeholders(values: list[str]) -> str:
    return ",".join("?" * len(values))


def _stored(params: tuple[object, ...], conn: sqlite3.Connection) -> tuple[object, ...]:
    """params with each datetime in the conversations columns' stored format."""
    return tuple(to_db(p, "local", conn) if isinstance(p, datetime) else p for p in params)


class ConversationTrashMixin:
    """Mixin providing conversation trash, restore and purge operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def delete_conversation(self, conv_id: str, user_id: str) -> bool:
        """Hard delete (defined in ConversationMixin)."""
        raise NotImplementedError

    def trash_conversation(self, conv_id: str, user_id: str) -> bool:
        """Move a conversation to the trash.

        Idempotent: trashing an already-trashed conversation succeeds and
        keeps the original deleted_at, so a retried DELETE neither 404s nor
        extends the retention window. updated_at is bumped (the trash list
        sorts by it); the old value is kept in trashed_updated_at for restore.
        """
        with self._pool.get_connection() as conn:
            now = to_db(utc_now(), "local", conn)
            cursor = self._execute_with_timing(
                conn,
                f"""UPDATE conversations SET {_TRASH_SET}
                   WHERE id = ? AND user_id = ?""",
                (now, now, conv_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def restore_conversation(self, conv_id: str, user_id: str) -> bool:
        """Take a conversation out of the trash, back where it was.

        archived/pinned are untouched, so an archived chat returns to the
        archive, and updated_at goes back to its pre-trash value, so the chat
        returns to its place in the list. Idempotent for live conversations
        (True, no change).
        """
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                f"""UPDATE conversations SET {_RESTORE_SET}
                   WHERE id = ? AND user_id = ?""",
                (conv_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def trash_conversations(self, user_id: str, ids: list[str]) -> list[str]:
        """Move the eligible rows among ids to the trash; returns the ids trashed."""
        if not ids:
            return []
        where = f"{_TRASHABLE_WHERE} AND id IN ({_placeholders(ids)})"
        return self._trash_where(where, (user_id, *ids))

    def trash_all_conversations(
        self,
        user_id: str,
        exclude_ids: list[str],
        created_before: datetime,
        extra_ids: list[str],
    ) -> list[str]:
        """Trash every unpinned main-list chat created before created_before,
        except exclude_ids, plus the eligible extra_ids (pinned chats picked by
        hand). created_before stops a chat started on another device after the
        user pressed Select all from being swept up."""
        all_set = f"""(pinned = 0 OR pinned IS NULL) AND (archived = 0 OR archived IS NULL)
            AND created_at < ? AND id NOT IN ({_placeholders(exclude_ids)})"""
        where = f"{_TRASHABLE_WHERE} AND (({all_set}) OR id IN ({_placeholders(extra_ids)}))"
        params = (user_id, created_before, *exclude_ids, *extra_ids)
        return self._trash_where(where, params)

    def restore_conversations(self, user_id: str, ids: list[str]) -> list[str]:
        """Take the user's trashed rows among ids out of the trash; returns them."""
        if not ids:
            return []
        where = f"user_id = ? AND deleted_at IS NOT NULL AND id IN ({_placeholders(ids)})"
        return self._update_where(where, (user_id, *ids), _RESTORE_SET, ())

    def _trash_where(self, where: str, params: tuple[Any, ...]) -> list[str]:
        now = utc_now()
        return self._update_where(where, params, _TRASH_SET, (now, now))

    def _update_where(
        self,
        where: str,
        params: tuple[Any, ...],
        set_clause: str,
        set_params: tuple[Any, ...],
    ) -> list[str]:
        """SELECT the matching ids, then UPDATE the same rows, under one write
        lock (BEGIN IMMEDIATE) so a concurrent change cannot slip between.

        Datetime params are stored in the columns' format (all local here)."""
        with self._pool.get_connection() as conn:
            params = _stored(params, conn)
            set_params = _stored(set_params, conn)
            self._execute_with_timing(conn, "BEGIN IMMEDIATE")
            try:
                rows = self._execute_with_timing(
                    conn, f"SELECT id FROM conversations WHERE {where}", params
                ).fetchall()
                if rows:
                    self._execute_with_timing(
                        conn,
                        f"UPDATE conversations SET {set_clause} WHERE {where}",
                        (*set_params, *params),
                    )
            except BaseException:
                conn.rollback()
                raise
            conn.commit()
        return [row["id"] for row in rows]

    def list_trashed_conversations_paginated(
        self,
        user_id: str,
        limit: int = 30,
        cursor: str | None = None,
    ) -> tuple[list[tuple[Conversation, int, str | None]], str | None, bool, int]:
        """Trashed conversations, most recently trashed first.

        Same shape as list_archived_conversations_paginated. Trashing bumps
        updated_at, so the shared (updated_at, id) cursor orders by trash time.
        """
        with self._pool.get_connection() as conn:
            total_row = self._execute_with_timing(
                conn,
                """SELECT COUNT(*) as count FROM conversations
                   WHERE user_id = ? AND deleted_at IS NOT NULL""",
                (user_id,),
            ).fetchone()
            total_count = int(total_row["count"]) if total_row else 0

            query = _TRASH_LIST_SELECT
            params: tuple[Any, ...] = (user_id,)
            if cursor:
                cursor_timestamp, cursor_id = parse_cursor(cursor)
                cursor_timestamp = normalize_cursor(cursor_timestamp, "local", conn)
                query += " AND (c.updated_at < ? OR (c.updated_at = ? AND c.id < ?))"
                params += (cursor_timestamp, cursor_timestamp, cursor_id)
            rows = self._execute_with_timing(
                conn,
                query + " GROUP BY c.id ORDER BY c.updated_at DESC, c.id DESC LIMIT ?",
                (*params, limit + 1),
            ).fetchall()

        rows, next_cursor, has_more = page_rows(rows, limit)
        summaries = [row_to_conversation_summary(row) for row in rows]
        return summaries, next_cursor, has_more, total_count

    def delete_trashed_conversation(self, conv_id: str, user_id: str) -> bool:
        """Permanently delete one conversation, only if it is in the trash."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT 1 FROM conversations
                   WHERE id = ? AND user_id = ? AND deleted_at IS NOT NULL""",
                (conv_id, user_id),
            ).fetchone()
        if not row:
            return False
        return self.delete_conversation(conv_id, user_id)

    def empty_trash(self, user_id: str) -> int:
        """Permanently delete all of a user's trashed conversations."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                "SELECT id FROM conversations WHERE user_id = ? AND deleted_at IS NOT NULL",
                (user_id,),
            ).fetchall()
        return self._purge_trashed(user_id, [row["id"] for row in rows])

    def purge_trashed_conversations(self, retention_days: int) -> int:
        """Permanently delete conversations trashed over retention_days ago (all users)."""
        with self._pool.get_connection() as conn:
            cutoff = to_db(utc_now() - timedelta(days=retention_days), "local", conn)
            rows = self._execute_with_timing(
                conn,
                """SELECT id, user_id FROM conversations
                   WHERE deleted_at IS NOT NULL AND deleted_at < ?""",
                (cutoff,),
            ).fetchall()
        by_user: dict[str, list[str]] = {}
        for row in rows:
            by_user.setdefault(row["user_id"], []).append(row["id"])
        purged = sum(self._purge_trashed(user_id, ids) for user_id, ids in by_user.items())
        if purged:
            logger.info("Purged trashed conversations", extra={"purged": purged})
        return purged

    def _purge_trashed(self, user_id: str, conv_ids: list[str]) -> int:
        """Hard-delete the user's conversations among conv_ids that are still
        in the trash, in chunks: rows first and committed, then blobs - a
        crash in between leaves only harmless orphaned blobs (as
        delete_conversation does). A chat restored meanwhile is skipped."""
        deleted = 0
        for start in range(0, len(conv_ids), _PURGE_CHUNK):
            chunk = conv_ids[start : start + _PURGE_CHUNK]
            with self._pool.get_connection() as conn:
                trashed = [
                    row["id"]
                    for row in self._execute_with_timing(
                        conn,
                        f"""SELECT id FROM conversations WHERE user_id = ?
                            AND deleted_at IS NOT NULL AND id IN ({_placeholders(chunk)})""",
                        (user_id, *chunk),
                    ).fetchall()
                ]
                if not trashed:
                    continue
                ids_sql = _placeholders(trashed)
                message_ids = [
                    row["id"]
                    for row in self._execute_with_timing(
                        conn,
                        f"SELECT id FROM messages WHERE conversation_id IN ({ids_sql})",
                        tuple(trashed),
                    ).fetchall()
                ]
                self._execute_with_timing(
                    conn,
                    f"DELETE FROM messages WHERE conversation_id IN ({ids_sql})",
                    tuple(trashed),
                )
                deleted += self._execute_with_timing(
                    conn,
                    f"DELETE FROM conversations WHERE user_id = ? AND id IN ({ids_sql})",
                    (user_id, *trashed),
                ).rowcount
                conn.commit()
            delete_messages_blobs(message_ids)
        return deleted
