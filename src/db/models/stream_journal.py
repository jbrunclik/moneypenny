"""Stream journal database operations mixin.

Persists chat-stream SSE events per assistant-message-id with monotonic
sequence numbers so interrupted clients can resume from an offset (see
src/api/helpers/chat_streaming.py and the resume endpoint in routes/chat.py).
Rows are short-lived: swept by journal_cleanup() at journal-start time.
"""

from __future__ import annotations

import sqlite3
import time
from typing import TYPE_CHECKING, Any

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class StreamJournalMixin:
    """Mixin providing stream journal operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def journal_append_events(self, message_id: str, events: list[tuple[int, str]]) -> None:
        """Append a batch of (seq, event_json) rows for a message's stream.

        Args:
            message_id: The assistant message id the stream belongs to
            events: (seq, serialized event) tuples, seq strictly increasing
        """
        if not events:
            return
        now = time.time()
        with self._pool.get_connection() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO stream_journal (message_id, seq, event, created_at)
                   VALUES (?, ?, ?, ?)""",
                [(message_id, seq, event, now) for seq, event in events],
            )
            conn.commit()

    def journal_get_events(self, message_id: str, after_seq: int) -> list[tuple[int, str]]:
        """Get journaled events for a message with seq greater than after_seq."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT seq, event FROM stream_journal
                   WHERE message_id = ? AND seq > ?
                   ORDER BY seq ASC""",
                (message_id, after_seq),
            ).fetchall()
            return [(row["seq"], row["event"]) for row in rows]

    def journal_cleanup(self, max_age_seconds: int) -> int:
        """Delete journal rows older than max_age_seconds. Returns rowcount."""
        cutoff = time.time() - max_age_seconds
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM stream_journal WHERE created_at < ?",
                (cutoff,),
            )
            conn.commit()
            return cursor.rowcount
