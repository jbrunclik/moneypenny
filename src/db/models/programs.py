"""Program-conversation database operations mixin (sports, language, ...).

Each "program feature" is a set of dedicated conversations flagged on the
conversations table (one conversation per user per program), with program
definitions and progress stored in the K/V store under the feature's
namespace. Sports and language shared two near-identical mixins; this is
the single parameterized replacement (Q2).
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.db.models.dataclasses import Conversation
from src.db.models.helpers import delete_messages_blobs
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


@dataclass(frozen=True)
class ProgramFeature:
    """Column/name mapping for one program feature."""

    namespace: str  # K/V namespace + API url segment
    flag_column: str  # conversations boolean column (is_sports, ...)
    program_column: str  # conversations program-id column (sports_program, ...)
    title_prefix: str  # conversation title prefix ("Sports: <program>")


# The ONLY source of column names interpolated into the SQL below - never
# user input. Adding a feature = one entry here + columns migration.
PROGRAM_FEATURES: dict[str, ProgramFeature] = {
    "sports": ProgramFeature("sports", "is_sports", "sports_program", "Sports"),
    "language": ProgramFeature("language", "is_language", "language_program", "Language"),
}


def _feature(namespace: str) -> ProgramFeature:
    try:
        return PROGRAM_FEATURES[namespace]
    except KeyError:
        raise ValueError(f"Unknown program feature: {namespace!r}") from None


class ProgramConversationMixin:
    """Mixin providing program-conversation database operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def _row_to_conversation(self, row: sqlite3.Row) -> Conversation:
        """Convert row to Conversation (defined in ConversationMixin)."""
        raise NotImplementedError

    def get_program_conversation(
        self, namespace: str, user_id: str, program: str
    ) -> Conversation | None:
        """Get the program conversation for a user and program, or None."""
        f = _feature(namespace)
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                f"SELECT * FROM conversations WHERE user_id = ? AND {f.flag_column} = 1 "
                f"AND {f.program_column} = ?",
                (user_id, program),
            ).fetchone()

            return self._row_to_conversation(row) if row else None

    def get_or_create_program_conversation(
        self, namespace: str, user_id: str, program: str, model: str | None = None
    ) -> Conversation:
        """Get or create the program conversation (one per user per program)."""
        f = _feature(namespace)
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                f"SELECT * FROM conversations WHERE user_id = ? AND {f.flag_column} = 1 "
                f"AND {f.program_column} = ?",
                (user_id, program),
            ).fetchone()

            if row:
                return self._row_to_conversation(row)

            conv_id = str(uuid.uuid4())
            model = model or Config.DEFAULT_MODEL
            now = datetime.now()
            title = f"{f.title_prefix}: {program}"

            self._execute_with_timing(
                conn,
                f"""INSERT INTO conversations
                   (id, user_id, title, model, {f.flag_column}, {f.program_column},
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
                (conv_id, user_id, title, model, program, now.isoformat(), now.isoformat()),
            )
            conn.commit()

            logger.info(
                "Program conversation created",
                extra={
                    "namespace": namespace,
                    "conversation_id": conv_id,
                    "user_id": user_id,
                    "program": program,
                },
            )
            extra_fields: dict[str, Any] = {
                f.flag_column: True,
                f.program_column: program,
            }
            return Conversation(
                id=conv_id,
                user_id=user_id,
                title=title,
                model=model,
                created_at=now,
                updated_at=now,
                **extra_fields,
            )

    def reset_program_conversation(
        self, namespace: str, user_id: str, program: str
    ) -> Conversation | None:
        """Reset a program conversation by deleting all messages.

        Preserves the conversation itself and cost data.
        """
        f = _feature(namespace)
        logger.info(
            "Resetting program conversation",
            extra={"namespace": namespace, "user_id": user_id, "program": program},
        )

        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                f"SELECT * FROM conversations WHERE user_id = ? AND {f.flag_column} = 1 "
                f"AND {f.program_column} = ?",
                (user_id, program),
            ).fetchone()

            if not row:
                return None

            conv_id = row["id"]

            message_rows = self._execute_with_timing(
                conn, "SELECT id FROM messages WHERE conversation_id = ?", (conv_id,)
            ).fetchall()
            message_ids = [r["id"] for r in message_rows]

            # Row deletes first; blob cleanup after commit (crash leaves only
            # harmless orphaned blobs, not rows pointing at deleted data)
            self._execute_with_timing(
                conn, "DELETE FROM messages WHERE conversation_id = ?", (conv_id,)
            )

            now = datetime.now()
            self._execute_with_timing(
                conn,
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now.isoformat(), conv_id),
            )

            conn.commit()

            if message_ids:
                delete_messages_blobs(message_ids)

            logger.info(
                "Program conversation reset",
                extra={
                    "namespace": namespace,
                    "conversation_id": conv_id,
                    "user_id": user_id,
                    "program": program,
                    "messages_deleted": len(message_ids),
                },
            )

            updated_row = self._execute_with_timing(
                conn, "SELECT * FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
            return self._row_to_conversation(updated_row) if updated_row else None

    def list_program_conversations(self, namespace: str, user_id: str) -> list[Conversation]:
        """List all of a user's conversations for this program feature."""
        f = _feature(namespace)
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                f"SELECT * FROM conversations WHERE user_id = ? AND {f.flag_column} = 1 "
                "ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()

            return [self._row_to_conversation(row) for row in rows]

    def delete_program_conversation(self, namespace: str, user_id: str, program: str) -> bool:
        """Delete a program conversation and all its messages."""
        f = _feature(namespace)
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                f"SELECT id FROM conversations WHERE user_id = ? AND {f.flag_column} = 1 "
                f"AND {f.program_column} = ?",
                (user_id, program),
            ).fetchone()

            if not row:
                return False

            conv_id = row["id"]

            message_rows = self._execute_with_timing(
                conn, "SELECT id FROM messages WHERE conversation_id = ?", (conv_id,)
            ).fetchall()
            message_ids = [r["id"] for r in message_rows]

            # Row deletes first; blob cleanup after commit
            self._execute_with_timing(
                conn, "DELETE FROM messages WHERE conversation_id = ?", (conv_id,)
            )
            self._execute_with_timing(
                conn,
                "DELETE FROM conversations WHERE id = ? AND user_id = ?",
                (conv_id, user_id),
            )
            conn.commit()

            if message_ids:
                delete_messages_blobs(message_ids)

            logger.info(
                "Program conversation deleted",
                extra={
                    "namespace": namespace,
                    "conversation_id": conv_id,
                    "user_id": user_id,
                    "program": program,
                },
            )
            return True
