"""Message pagination database operations mixin (cursor windows)."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from src.api.schemas.common import PaginationDirection
from src.db.models.dataclasses import Message, MessagePagination
from src.db.models.helpers import build_cursor, parse_cursor
from src.db.models.message_rows import row_to_message

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool


def _build_pagination(
    messages: list[Message], has_older: bool, has_newer: bool, total_count: int
) -> MessagePagination:
    """Pagination info for a chronologically ordered (oldest first) page."""
    if messages:
        # The oldest message in results becomes the "older_cursor"
        first_msg = messages[0]
        older_cursor = build_cursor(first_msg.created_at.isoformat(), first_msg.id)

        # The newest message in results becomes the "newer_cursor"
        last_msg = messages[-1]
        newer_cursor = build_cursor(last_msg.created_at.isoformat(), last_msg.id)
    else:
        older_cursor = None
        newer_cursor = None

    return MessagePagination(
        older_cursor=older_cursor if has_older else None,
        newer_cursor=newer_cursor if has_newer else None,
        has_older=has_older,
        has_newer=has_newer,
        total_count=total_count,
    )


class MessagePaginationMixin:
    """Mixin providing cursor-based, bi-directional message pagination."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def _count_messages(self, conn: sqlite3.Connection, conversation_id: str) -> int:
        """Total number of messages in a conversation."""
        total_row = self._execute_with_timing(
            conn,
            "SELECT COUNT(*) as count FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        return int(total_row["count"]) if total_row else 0

    def _fetch_page_rows(
        self,
        conn: sqlite3.Connection,
        conversation_id: str,
        limit: int,
        cursor: str | None,
        direction: PaginationDirection,
    ) -> list[sqlite3.Row]:
        """Fetch up to limit + 1 rows for one page, in query order."""
        if not cursor:
            # No cursor: return newest messages (for initial load)
            # Order by created_at DESC to get newest first, then reverse for display
            return self._execute_with_timing(
                conn,
                """SELECT * FROM messages
                   WHERE conversation_id = ?
                   ORDER BY created_at DESC, id DESC
                   LIMIT ?""",
                (conversation_id, limit + 1),
            ).fetchall()

        cursor_timestamp, cursor_id = parse_cursor(cursor)
        if direction == PaginationDirection.OLDER:
            # Fetch messages OLDER than cursor (created_at < cursor_timestamp)
            # Order by created_at DESC to get the ones just before cursor
            return self._execute_with_timing(
                conn,
                """SELECT * FROM messages
                   WHERE conversation_id = ?
                     AND (created_at < ? OR (created_at = ? AND id < ?))
                   ORDER BY created_at DESC, id DESC
                   LIMIT ?""",
                (conversation_id, cursor_timestamp, cursor_timestamp, cursor_id, limit + 1),
            ).fetchall()

        # direction == PaginationDirection.NEWER
        # Fetch messages NEWER than cursor (created_at > cursor_timestamp)
        # Order by created_at ASC to get the ones just after cursor
        return self._execute_with_timing(
            conn,
            """SELECT * FROM messages
               WHERE conversation_id = ?
                 AND (created_at > ? OR (created_at = ? AND id > ?))
               ORDER BY created_at ASC, id ASC
               LIMIT ?""",
            (conversation_id, cursor_timestamp, cursor_timestamp, cursor_id, limit + 1),
        ).fetchall()

    def get_messages_paginated(
        self,
        conversation_id: str,
        limit: int = 50,
        cursor: str | None = None,
        direction: PaginationDirection = PaginationDirection.OLDER,
    ) -> tuple[list[Message], MessagePagination]:
        """Get messages for a conversation with cursor-based pagination.

        By default, returns the newest messages (no cursor) or messages
        older/newer than the cursor position.

        Args:
            conversation_id: The conversation ID
            limit: Maximum number of messages to return
            cursor: Optional cursor from previous page (format: '{created_at}:{id}')
            direction: PaginationDirection.OLDER to get messages before cursor,
                      PaginationDirection.NEWER for after

        Returns:
            Tuple of:
            - List of Message objects (oldest first within the returned page)
            - MessagePagination info with cursors and flags
        """
        with self._pool.get_connection() as conn:
            total_count = self._count_messages(conn, conversation_id)
            rows = self._fetch_page_rows(conn, conversation_id, limit, cursor, direction)

            # Check if there are more in the direction we're paginating
            has_more_in_direction = len(rows) > limit
            if has_more_in_direction:
                rows = rows[:limit]

            messages = [row_to_message(row) for row in rows]

            # For display, we want messages in chronological order (oldest first)
            # When loading older or initial (newest first in query), we need to reverse
            if not cursor or direction == PaginationDirection.OLDER:
                messages = list(reversed(messages))

            # Determine has_older and has_newer
            if not cursor:
                # Initial load (newest messages): has_older if we got more, has_newer is False
                has_older = has_more_in_direction
                has_newer = False
            elif direction == PaginationDirection.OLDER:
                # Loading older: has_older if we got more, need to check has_newer separately
                has_older = has_more_in_direction
                # There are newer messages if we had a cursor (we came from somewhere)
                has_newer = True
            else:  # direction == PaginationDirection.NEWER
                # Loading newer: has_newer if we got more, has_older is True (we came from somewhere)
                has_newer = has_more_in_direction
                has_older = True

            return messages, _build_pagination(messages, has_older, has_newer, total_count)

    def get_messages_around(
        self,
        conversation_id: str,
        message_id: str,
        before_limit: int = 25,
        after_limit: int = 25,
    ) -> tuple[list[Message], MessagePagination] | None:
        """Get messages around a specific message.

        Loads messages before and after the target message to create a "window"
        centered on the target. Used for efficient search result navigation.

        Args:
            conversation_id: The conversation ID
            message_id: The target message ID to center around
            before_limit: Number of messages to load before the target (inclusive)
            after_limit: Number of messages to load after the target

        Returns:
            Tuple of (messages, pagination) or None if message not found.
            Messages are returned in chronological order (oldest first).
            Pagination includes both older_cursor and newer_cursor for
            bi-directional pagination from the loaded window.
        """
        with self._pool.get_connection() as conn:
            total_count = self._count_messages(conn, conversation_id)

            # Get the target message to verify it exists and get its timestamp
            target_row = self._execute_with_timing(
                conn,
                "SELECT id, created_at FROM messages WHERE id = ? AND conversation_id = ?",
                (message_id, conversation_id),
            ).fetchone()

            if not target_row:
                return None

            target_timestamp = target_row["created_at"]
            target_id = target_row["id"]

            # Get messages before and including the target
            # (created_at < target) OR (created_at = target AND id <= target_id)
            # Order DESC to get the closest ones, then reverse
            before_rows = self._execute_with_timing(
                conn,
                """SELECT * FROM messages
                   WHERE conversation_id = ?
                     AND (created_at < ? OR (created_at = ? AND id <= ?))
                   ORDER BY created_at DESC, id DESC
                   LIMIT ?""",
                (conversation_id, target_timestamp, target_timestamp, target_id, before_limit + 1),
            ).fetchall()

            # Check if there are older messages beyond what we fetched
            has_older = len(before_rows) > before_limit
            if has_older:
                before_rows = before_rows[:before_limit]

            # Get messages after the target (excluding target itself)
            # (created_at > target) OR (created_at = target AND id > target_id)
            after_rows = self._execute_with_timing(
                conn,
                """SELECT * FROM messages
                   WHERE conversation_id = ?
                     AND (created_at > ? OR (created_at = ? AND id > ?))
                   ORDER BY created_at ASC, id ASC
                   LIMIT ?""",
                (conversation_id, target_timestamp, target_timestamp, target_id, after_limit + 1),
            ).fetchall()

            # Check if there are newer messages beyond what we fetched
            has_newer = len(after_rows) > after_limit
            if has_newer:
                after_rows = after_rows[:after_limit]

            # Combine: reverse before_rows (they're DESC) + after_rows (already ASC)
            all_rows = list(reversed(before_rows)) + list(after_rows)
            messages = [row_to_message(row) for row in all_rows]

            return messages, _build_pagination(messages, has_older, has_newer, total_count)
