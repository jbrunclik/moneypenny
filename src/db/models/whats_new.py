"""What's new: the user's read-only announcements chat and the record of
which announcement reached whom (docs/features/whats-new.md)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from src.config import Config
from src.db.models.conversation_rows import row_to_conversation
from src.db.models.dataclasses import Conversation, User
from src.db.models.timestamps import to_db
from src.utils.clock import utc_now

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool


class WhatsNewMixin:
    """Mixin providing the What's new chat and announcement claims."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[object, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    if TYPE_CHECKING:

        def get_user_by_id(self, user_id: str) -> User | None:
            """Defined in UserMixin."""

    def users_joined_by(self, moment: datetime) -> list[User]:
        """Every user created at or before a moment (an announcement's audience)."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                "SELECT id FROM users WHERE created_at <= ? ORDER BY created_at",
                (to_db(moment),),
            ).fetchall()
        users = [self.get_user_by_id(row["id"]) for row in rows]
        return [u for u in users if u is not None]

    def claim_announcement(self, user_id: str, announcement_id: str) -> bool:
        """Record that an announcement goes to a user: True for the one caller
        that records it, False when it was posted (or is being posted) already."""
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """INSERT OR IGNORE INTO announcement_posts (user_id, announcement_id, posted_at)
                   VALUES (?, ?, ?)""",
                (user_id, announcement_id, to_db(utc_now())),
            )
            conn.commit()
        return cursor.rowcount == 1

    def set_announcement_message(self, user_id: str, announcement_id: str, message_id: str) -> None:
        """Remember the message a post became (a revision rewrites it)."""
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """UPDATE announcement_posts SET message_id = ?
                   WHERE user_id = ? AND announcement_id = ?""",
                (message_id, user_id, announcement_id),
            )
            conn.commit()

    def announcement_messages(self, announcement_id: str) -> list[tuple[str, str]]:
        """(user id, message id) of each post of an announcement that has one."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT user_id, message_id FROM announcement_posts
                   WHERE announcement_id = ? AND message_id IS NOT NULL""",
                (announcement_id,),
            ).fetchall()
        return [(row["user_id"], row["message_id"]) for row in rows]

    def revise_message_text(self, message_id: str, content: str, language: str) -> bool:
        """Rewrite a posted announcement's text in place - True when it changed.

        Unlike update_message_content it leaves the chat's updated_at alone,
        so a revision never moves the chat up the list; the sync trigger on
        messages still tells other devices.
        """
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE messages SET content = ?, language = ?
                   WHERE id = ? AND (content IS NOT ? OR language IS NOT ?)""",
                (content, language, message_id, content, language),
            )
            conn.commit()
        return cursor.rowcount == 1

    def release_announcement(self, user_id: str, announcement_id: str) -> None:
        """Undo a claim whose post failed, so the next start tries again."""
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                "DELETE FROM announcement_posts WHERE user_id = ? AND announcement_id = ?",
                (user_id, announcement_id),
            )
            conn.commit()

    def get_whats_new_conversation(self, user_id: str) -> Conversation | None:
        """The user's live What's new chat (archived or not; never a trashed one)."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT * FROM conversations
                   WHERE user_id = ? AND is_whats_new = 1 AND deleted_at IS NULL
                   ORDER BY created_at DESC LIMIT 1""",
                (user_id,),
            ).fetchone()
        return row_to_conversation(row) if row else None

    def whats_new_conversation_for_post(self, user_id: str, title: str) -> str:
        """The chat a new announcement goes into: the live one, unarchived,
        or a fresh one (never made, or the user deleted it)."""
        existing = self.get_whats_new_conversation(user_id)
        with self._pool.get_connection() as conn:
            if existing is not None:
                if existing.archived:
                    self._execute_with_timing(
                        conn,
                        "UPDATE conversations SET archived = 0 WHERE id = ? AND user_id = ?",
                        (existing.id, user_id),
                    )
                    conn.commit()
                return existing.id
            conv_id = str(uuid.uuid4())
            now = to_db(utc_now())
            self._execute_with_timing(
                conn,
                """INSERT INTO conversations
                   (id, user_id, title, model, created_at, updated_at, is_whats_new)
                   VALUES (?, ?, ?, ?, ?, ?, 1)""",
                (conv_id, user_id, title, Config.DEFAULT_MODEL, now, now),
            )
            conn.commit()
        return conv_id
