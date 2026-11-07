"""Reminders set from chat: stored, listed, cancelled, and claimed when due.

claim_due_reminders flips due pending rows to "sent" in one UPDATE ...
RETURNING, so two overlapping scheduler runs never push one twice.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from src.db.models.dataclasses import Reminder
from src.db.models.timestamps import from_db, to_db
from src.utils.clock import utc_now

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool


def _row_to_reminder(row: sqlite3.Row) -> Reminder:
    return Reminder(
        id=row["id"],
        user_id=row["user_id"],
        conversation_id=row["conversation_id"],
        text=row["text"],
        due_at=from_db(row["due_at"]),
        status=row["status"],
        created_at=from_db(row["created_at"]),
    )


class RemindersMixin:
    """Reminder rows for the schedule tool and the scheduler."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self, conn: sqlite3.Connection, query: str, params: tuple[object, ...] = ()
    ) -> sqlite3.Cursor:
        raise NotImplementedError

    def add_reminder(
        self, user_id: str, conversation_id: str | None, text: str, due_at: datetime
    ) -> Reminder:
        reminder = Reminder(
            str(uuid.uuid4()), user_id, conversation_id, text, due_at, "pending", utc_now()
        )
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO reminders (id, user_id, conversation_id, text, due_at, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    reminder.id,
                    user_id,
                    conversation_id,
                    text,
                    to_db(due_at),
                    to_db(reminder.created_at),
                ),
            )
            conn.commit()
        return reminder

    def list_reminders(self, user_id: str, status: str = "pending") -> list[Reminder]:
        """The user's reminders with this status, soonest first."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                "SELECT * FROM reminders WHERE user_id = ? AND status = ? ORDER BY due_at",
                (user_id, status),
            ).fetchall()
        return [_row_to_reminder(row) for row in rows]

    def cancel_reminder(self, reminder_id: str, user_id: str) -> bool:
        """Cancel one of the user's pending reminders; False if none matched."""
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE reminders SET status = 'cancelled'
                   WHERE id = ? AND user_id = ? AND status = 'pending'""",
                (reminder_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def claim_due_reminders(self, now: datetime) -> list[Reminder]:
        """Mark every pending reminder due by `now` as sent, and return them."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """UPDATE reminders SET status = 'sent'
                   WHERE status = 'pending' AND due_at <= ?
                   RETURNING *""",
                (to_db(now),),
            ).fetchall()
            conn.commit()
        return sorted((_row_to_reminder(row) for row in rows), key=lambda r: r.due_at)
