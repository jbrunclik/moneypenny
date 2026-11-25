"""Memory database operations mixin.

Contains all methods for UserMemory entity management including:
- CRUD operations
- Bulk updates (for defragmentation)
- User queries with memory counts
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, Literal

from src.config import Config
from src.db.models.dataclasses import Memory, User
from src.db.models.helpers import is_live_project_member
from src.db.models.timestamps import from_db, from_db_or_none, to_db
from src.utils.clock import local_today, utc_now
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


@dataclass(frozen=True)
class MemoryWrite:
    """One validated write for apply_memory_batch.

    add: content + category. patch: the full new content, the content it was
    computed from (expected), and an optional new category. delete: the id.
    valid_until (add, patch): an ISO date, "" to clear it, None to leave it.
    """

    action: Literal["add", "patch", "delete"]
    memory_id: str | None = None
    content: str | None = None
    expected: str | None = None
    category: str | None = None
    valid_until: str | None = None
    # add: the project the memory is filed under (None = personal)
    project_id: str | None = None


# A memory row the user may change from the Data page or a project page: their
# personal one, or one of a live project they are a member of
_VISIBLE_SQL = """((user_id = ? AND project_id IS NULL) OR project_id IN (
    SELECT pm.project_id FROM project_members pm JOIN projects p ON p.id = pm.project_id
    WHERE pm.user_id = ? AND p.deleted_at IS NULL))"""
# A memory row a chat turn may change: personal, or of the chat's own project
_IN_SCOPE_SQL = "((user_id = ? AND project_id IS NULL) OR project_id = ?)"
_PERSONAL_SQL = "user_id = ? AND project_id IS NULL"


class MemoryLimitError(Exception):
    """A batch would pass a project's PROJECT_MEMORY_MAX_ENTRIES."""


class MemoryScopeError(Exception):
    """A batch adds to a project the user is no longer a member of."""


class MemoryWriteConflictError(Exception):
    """A batch target changed or vanished after the batch was planned."""

    def __init__(self, memory_id: str) -> None:
        super().__init__(f"memory {memory_id} changed or was deleted meanwhile")
        self.memory_id = memory_id


class InstructionsWriteConflictError(Exception):
    """The user's custom instructions changed after the change was planned."""


class MemoryMixin:
    """Mixin providing Memory-related database operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def add_memory(
        self,
        user_id: str,
        content: str,
        category: str | None = None,
        source_conversation_id: str | None = None,
        protected: bool = False,
    ) -> Memory:
        """Add a memory for a user.

        Args:
            user_id: The user ID
            content: The memory content
            category: Optional category (preference, fact, context, goal)
            source_conversation_id: Conversation the memory was learned in
            protected: If True, the memory is exempt from LLM/defrag deletion

        Returns:
            The created Memory
        """
        memory_id = str(uuid.uuid4())
        now = utc_now()
        logger.debug(
            "Adding memory",
            extra={"user_id": user_id, "memory_id": memory_id, "category": category},
        )

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO user_memories
                   (id, user_id, content, category, created_at, updated_at,
                    source_conversation_id, protected)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    memory_id,
                    user_id,
                    content,
                    category,
                    to_db(now),
                    to_db(now),
                    source_conversation_id,
                    int(protected),
                ),
            )
            conn.commit()

        logger.info("Memory added", extra={"memory_id": memory_id, "user_id": user_id})
        return Memory(
            id=memory_id,
            user_id=user_id,
            content=content,
            category=category,
            created_at=now,
            updated_at=now,
            protected=protected,
            source_conversation_id=source_conversation_id,
        )

    def apply_memory_batch(
        self,
        user_id: str,
        conversation_id: str | None,
        writes: list[MemoryWrite],
        project_id: str | None = None,
    ) -> list[str | None]:
        """Apply manage_memory's writes in one transaction: all of them or none.

        A patch carries the content it was computed from and lands only if the
        row still holds it, so an edit made in between (another device, a
        defrag run) is never overwritten. Deletes refuse protected rows. Any
        miss rolls everything back and raises MemoryWriteConflictError.

        ``project_id`` is the chat's project: patches and deletes may touch
        the user's personal memories and that project's (any member's).

        Returns:
            The new memory id for each add, None for the other writes

        Raises:
            MemoryWriteConflictError: a target changed, vanished or is out of scope
            MemoryLimitError: the batch would pass the project's memory cap
            MemoryScopeError: an add targets a project the user has left
        """
        now = to_db(utc_now())
        new_ids: list[str | None] = []
        with self._pool.get_connection() as conn:
            self._execute_with_timing(conn, "BEGIN IMMEDIATE")
            try:
                project_id = self._checked_scope(conn, user_id, writes, project_id)
                new_ids.extend(
                    self._apply_memory_write(conn, user_id, conversation_id, write, now, project_id)
                    for write in writes
                )
                self._check_project_caps(conn, {w.project_id for w in writes if w.project_id})
            except BaseException:
                conn.rollback()
                raise
            conn.commit()
        logger.info("Memory batch applied", extra={"user_id": user_id, "writes": len(writes)})
        return new_ids

    def apply_instructions_change(
        self,
        user_id: str,
        expected_instructions: str,
        new_instructions: str | None,
        writes: list[MemoryWrite],
    ) -> list[str | None]:
        """Set the custom instructions and apply memory writes in one transaction.

        The instructions land only while the row still holds
        ``expected_instructions`` (the text the change was computed from); a
        memory write that misses rolls everything back, like apply_memory_batch.

        Returns:
            The new memory id for each add, None for the other writes

        Raises:
            InstructionsWriteConflictError: the instructions changed meanwhile
            MemoryWriteConflictError: a memory target changed or vanished
        """
        now = to_db(utc_now())
        with self._pool.get_connection() as conn:
            self._execute_with_timing(conn, "BEGIN IMMEDIATE")
            try:
                cursor = self._execute_with_timing(
                    conn,
                    """UPDATE users SET custom_instructions = ?
                       WHERE id = ? AND COALESCE(custom_instructions, '') = ?""",
                    (new_instructions, user_id, expected_instructions),
                )
                if cursor.rowcount == 0:
                    raise InstructionsWriteConflictError(user_id)
                new_ids = [self._apply_memory_write(conn, user_id, None, w, now) for w in writes]
            except BaseException:
                conn.rollback()
                raise
            conn.commit()
        return new_ids

    def _checked_scope(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        writes: list[MemoryWrite],
        project_id: str | None,
    ) -> str | None:
        """Membership, read inside the write transaction: an add to a project
        the user has left is refused; patches and deletes then reach only
        personal memories."""
        for target in {w.project_id for w in writes if w.project_id}:
            if not is_live_project_member(conn, target, user_id):
                raise MemoryScopeError("you are no longer a member of that project")
        if project_id is not None and not is_live_project_member(conn, project_id, user_id):
            return None
        return project_id

    def _check_project_caps(self, conn: sqlite3.Connection, project_ids: set[str]) -> None:
        """Refuse a batch that leaves a project past its memory cap."""
        limit = Config.PROJECT_MEMORY_MAX_ENTRIES
        for project_id in project_ids:
            count = self._execute_with_timing(
                conn,
                "SELECT COUNT(*) FROM user_memories WHERE project_id = ? AND deleted_at IS NULL",
                (project_id,),
            ).fetchone()[0]
            if count > limit:
                raise MemoryLimitError(
                    f"the project memory is full ({limit} entries): merge or delete some first"
                )

    def _apply_memory_write(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        conversation_id: str | None,
        write: MemoryWrite,
        now: str,
        project_id: str | None = None,
    ) -> str | None:
        """One write inside apply_memory_batch's transaction."""
        if write.action == "add":
            memory_id = str(uuid.uuid4())
            self._execute_with_timing(
                conn,
                """INSERT INTO user_memories
                   (id, user_id, content, category, created_at, updated_at,
                    source_conversation_id, protected, valid_until, project_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULLIF(?, ''), ?)""",
                (
                    memory_id,
                    user_id,
                    write.content,
                    write.category,
                    now,
                    now,
                    conversation_id,
                    write.valid_until,
                    write.project_id,
                ),
            )
            return memory_id
        if write.action == "patch":
            cursor = self._execute_with_timing(
                conn,
                """UPDATE user_memories
                   SET content = ?, category = COALESCE(?, category), updated_at = ?,
                       valid_until = CASE WHEN ? IS NULL THEN valid_until ELSE NULLIF(?, '') END
                   WHERE id = ? AND """
                + _IN_SCOPE_SQL
                + """ AND content = ? AND deleted_at IS NULL""",
                (
                    write.content,
                    write.category,
                    now,
                    write.valid_until,
                    write.valid_until,
                    write.memory_id,
                    user_id,
                    project_id,
                    write.expected,
                ),
            )
        else:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE user_memories SET deleted_at = ?
                   WHERE id = ? AND """
                + _IN_SCOPE_SQL
                + """ AND deleted_at IS NULL AND protected = 0
                     AND (? IS NULL OR content = ?)""",
                (now, write.memory_id, user_id, project_id, write.expected, write.expected),
            )
        if cursor.rowcount == 0:
            raise MemoryWriteConflictError(str(write.memory_id))
        return None

    def set_memory_protected(self, memory_id: str, user_id: str, protected: bool) -> bool:
        """Mark a memory as protected (exempt from LLM/defrag deletion).

        Args:
            memory_id: The memory ID
            user_id: The user ID (for ownership verification)
            protected: Whether the memory should be protected

        Returns:
            True if memory was updated, False if not found
        """
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                f"""UPDATE user_memories SET protected = ?
                   WHERE id = ? AND {_VISIBLE_SQL} AND deleted_at IS NULL""",
                (int(protected), memory_id, user_id, user_id),
            )
            conn.commit()
            updated = cursor.rowcount > 0

        if updated:
            logger.info(
                "Memory protection changed",
                extra={"memory_id": memory_id, "user_id": user_id, "protected": protected},
            )
        return updated

    def delete_memory(self, memory_id: str, user_id: str, *, allow_protected: bool = False) -> bool:
        """Soft-delete a memory.

        The row is retained (``deleted_at`` set) so an unwanted delete - from a
        bad defrag run or an LLM acting on injected content - can be recovered
        until the nightly purge. Protected memories are refused unless
        ``allow_protected`` is set, which only user-initiated deletes do.

        Args:
            memory_id: The memory ID
            user_id: The user ID (for ownership verification)
            allow_protected: Permit deleting a protected memory

        Returns:
            True if memory was deleted, False if not found or protected
        """
        logger.debug(
            "Deleting memory",
            extra={"user_id": user_id, "memory_id": memory_id},
        )

        query = f"""UPDATE user_memories SET deleted_at = ?
                   WHERE id = ? AND {_VISIBLE_SQL} AND deleted_at IS NULL"""
        if not allow_protected:
            query += " AND protected = 0"

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                query,
                (to_db(utc_now()), memory_id, user_id, user_id),
            )
            conn.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info("Memory deleted", extra={"memory_id": memory_id, "user_id": user_id})
        else:
            logger.warning(
                "Memory not deleted - not found or protected",
                extra={"memory_id": memory_id, "user_id": user_id},
            )
        return deleted

    def restore_memory(self, memory_id: str, user_id: str) -> bool:
        """Undo a soft delete, provided the row has not been purged yet. An
        expired memory comes back without its end date (or it would expire
        again the next night).

        Args:
            memory_id: The memory ID
            user_id: The user ID (for ownership verification)

        Returns:
            True if memory was restored, False if not found or not deleted
        """
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                f"""UPDATE user_memories SET deleted_at = NULL,
                       valid_until = CASE WHEN valid_until < ? THEN NULL ELSE valid_until END
                   WHERE id = ? AND {_VISIBLE_SQL} AND deleted_at IS NOT NULL""",
                (local_today().isoformat(), memory_id, user_id, user_id),
            )
            conn.commit()
            restored = cursor.rowcount > 0

        if restored:
            logger.info("Memory restored", extra={"memory_id": memory_id, "user_id": user_id})
        return restored

    def restore_previous_memory(self, memory_id: str, user_id: str) -> Memory | None:
        """Put a live memory's previous text back. The two texts swap (the
        trigger keeps the replaced one), so a restore can itself be undone.

        Returns:
            The memory as restored, or None if not found, deleted or without
            a previous text
        """
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                f"""UPDATE user_memories SET content = previous_content, updated_at = ?
                   WHERE id = ? AND {_VISIBLE_SQL} AND deleted_at IS NULL
                     AND previous_content IS NOT NULL""",
                (to_db(utc_now()), memory_id, user_id, user_id),
            )
            conn.commit()
        if cursor.rowcount == 0:
            return None
        logger.info(
            "Memory previous text restored", extra={"memory_id": memory_id, "user_id": user_id}
        )
        return self.get_visible_memory(memory_id, user_id)

    def expire_memories(self, today: date) -> int:
        """Soft-delete live memories whose last day (valid_until) is before
        ``today``; they land in the Deleted list like any other delete.
        Protected memories stay (only the user deletes those).

        Returns:
            Number of memories expired
        """
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE user_memories SET deleted_at = ?
                   WHERE deleted_at IS NULL AND protected = 0
                     AND valid_until IS NOT NULL AND valid_until < ?""",
                (to_db(utc_now()), today.isoformat()),
            )
            conn.commit()
            return int(cursor.rowcount)

    def purge_deleted_memories(self, retention_days: int) -> int:
        """Hard-delete soft-deleted memories past the retention window.

        Args:
            retention_days: Days to retain soft-deleted rows

        Returns:
            Number of rows purged
        """
        with self._pool.get_connection() as conn:
            cutoff = to_db(utc_now() - timedelta(days=retention_days))
            cursor = self._execute_with_timing(
                conn,
                # A deleted project's memories wait for the project's own purge
                # (restorable with it for DOCUMENTS_SOFT_DELETE_RETENTION_DAYS)
                """DELETE FROM user_memories WHERE deleted_at IS NOT NULL AND deleted_at < ?
                   AND (project_id IS NULL OR project_id NOT IN (
                       SELECT id FROM projects WHERE deleted_at IS NOT NULL))""",
                (cutoff,),
            )
            conn.commit()
            purged = int(cursor.rowcount)

        if purged:
            logger.info(
                "Purged soft-deleted memories",
                extra={"purged": purged, "retention_days": retention_days},
            )
        return purged

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        """Build a Memory from a user_memories row."""
        return Memory(
            id=row["id"],
            user_id=row["user_id"],
            content=row["content"],
            category=row["category"],
            created_at=from_db(row["created_at"]),
            updated_at=from_db(row["updated_at"]),
            protected=bool(row["protected"]),
            source_conversation_id=row["source_conversation_id"],
            deleted_at=from_db_or_none(row["deleted_at"]),
            summary=row["summary"],
            valid_until=date.fromisoformat(row["valid_until"]) if row["valid_until"] else None,
            previous_content=row["previous_content"],
            project_id=row["project_id"],
        )

    def memories_needing_summary(self, min_chars: int, limit: int) -> list[Memory]:
        """Live memories longer than ``min_chars`` without a summary (any user)."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM user_memories
                   WHERE deleted_at IS NULL AND summary IS NULL AND length(content) > ?
                   ORDER BY updated_at DESC LIMIT ?""",
                (min_chars, limit),
            ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    def set_memory_summary(self, memory_id: str, content: str, summary: str) -> bool:
        """Store a summary of ``content`` - only while the memory still holds
        that text (one edited meanwhile keeps none until the next pass)."""
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE user_memories SET summary = ? WHERE id = ? AND content = ?",
                (summary, memory_id, content),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_memory(self, memory_id: str, user_id: str) -> Memory | None:
        """Fetch a single live memory.

        Args:
            memory_id: The memory ID
            user_id: The user ID (for ownership verification)

        Returns:
            The Memory, or None if not found or soft-deleted
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                f"""SELECT * FROM user_memories
                   WHERE id = ? AND {_PERSONAL_SQL} AND deleted_at IS NULL""",
                (memory_id, user_id),
            ).fetchone()

            return self._row_to_memory(row) if row else None

    def get_memory_in_scope(
        self, memory_id: str, user_id: str, project_id: str | None
    ) -> Memory | None:
        """A live memory a chat turn may use: personal, or of ``project_id``
        (the chat's project; the caller has checked membership)."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                f"""SELECT * FROM user_memories
                   WHERE id = ? AND {_IN_SCOPE_SQL} AND deleted_at IS NULL""",
                (memory_id, user_id, project_id),
            ).fetchone()
            return self._row_to_memory(row) if row else None

    def get_visible_memory(self, memory_id: str, user_id: str) -> Memory | None:
        """A live memory the user may see in the app: personal, or of a live
        project they are a member of."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                f"""SELECT * FROM user_memories
                   WHERE id = ? AND {_VISIBLE_SQL} AND deleted_at IS NULL""",
                (memory_id, user_id, user_id),
            ).fetchone()
            return self._row_to_memory(row) if row else None

    def list_memories(self, user_id: str) -> list[Memory]:
        """List all live memories for a user.

        Args:
            user_id: The user ID

        Returns:
            List of Memory objects, ordered by updated_at DESC
        """
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                f"""SELECT * FROM user_memories WHERE {_PERSONAL_SQL} AND deleted_at IS NULL
                   ORDER BY updated_at DESC""",
                (user_id,),
            ).fetchall()

            return [self._row_to_memory(row) for row in rows]

    def list_project_memories(self, project_id: str) -> list[Memory]:
        """A project's live memories (every member's), newest first. The
        caller has checked membership."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM user_memories WHERE project_id = ? AND deleted_at IS NULL
                   ORDER BY updated_at DESC""",
                (project_id,),
            ).fetchall()
            return [self._row_to_memory(row) for row in rows]

    def list_deleted_project_memories(self, project_id: str) -> list[Memory]:
        """A project's soft-deleted memories still restorable, most recent first."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM user_memories WHERE project_id = ? AND deleted_at IS NOT NULL
                   ORDER BY deleted_at DESC""",
                (project_id,),
            ).fetchall()
            return [self._row_to_memory(row) for row in rows]

    def list_deleted_memories(self, user_id: str) -> list[Memory]:
        """List soft-deleted memories still inside the retention window.

        Args:
            user_id: The user ID

        Returns:
            List of Memory objects, most recently deleted first
        """
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                f"""SELECT * FROM user_memories WHERE {_PERSONAL_SQL} AND deleted_at IS NOT NULL
                   ORDER BY deleted_at DESC""",
                (user_id,),
            ).fetchall()

            return [self._row_to_memory(row) for row in rows]

    def get_memory_count(self, user_id: str) -> int:
        """Get the count of live memories for a user.

        Args:
            user_id: The user ID

        Returns:
            Number of memories
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                f"""SELECT COUNT(*) as count FROM user_memories
                   WHERE {_PERSONAL_SQL} AND deleted_at IS NULL""",
                (user_id,),
            ).fetchone()

            return int(row["count"]) if row else 0

    def get_users_with_memory_counts(self, min_memories: int = 0) -> list[tuple[User, int]]:
        """Get all users with their memory counts.

        Used by memory defragmentation to find users who need cleanup.

        Args:
            min_memories: Only return users with at least this many memories

        Returns:
            List of (User, memory_count) tuples, ordered by memory count descending
        """
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """
                SELECT u.*, COUNT(m.id) as memory_count
                FROM users u
                LEFT JOIN user_memories m
                  ON u.id = m.user_id AND m.deleted_at IS NULL AND m.project_id IS NULL
                GROUP BY u.id
                HAVING COUNT(m.id) >= ?
                ORDER BY memory_count DESC
                """,
                (min_memories,),
            ).fetchall()

            return [
                (
                    User(
                        id=row["id"],
                        email=row["email"],
                        name=row["name"],
                        picture=row["picture"],
                        created_at=from_db(row["created_at"]),
                        custom_instructions=row["custom_instructions"],
                    ),
                    int(row["memory_count"]),
                )
                for row in rows
            ]

    def bulk_update_memories(
        self,
        user_id: str,
        to_delete: list[str],
        to_update: list[tuple[str, str, str | None]],
        to_add: list[tuple[str, str | None]],
    ) -> dict[str, int]:
        """Bulk update memories for a user (used by defragmentation).

        Performs deletions, updates, and additions in a single transaction.
        Deletes are soft and skip protected memories, so a bad consolidation
        run cannot destroy identity facts.

        Args:
            user_id: The user ID
            to_delete: List of memory IDs to delete
            to_update: List of (memory_id, new_content, category) tuples
            to_add: List of (content, category) tuples for new memories

        Returns:
            Dict with counts: {"deleted": N, "updated": N, "added": N}
        """
        result = {"deleted": 0, "updated": 0, "added": 0}

        with self._pool.get_connection() as conn:
            now = to_db(utc_now())
            # Soft-delete memories, skipping protected ones
            for memory_id in to_delete:
                cursor = self._execute_with_timing(
                    conn,
                    """
                    UPDATE user_memories SET deleted_at = ?
                    WHERE id = ? AND user_id = ? AND project_id IS NULL
                      AND deleted_at IS NULL AND protected = 0
                    """,
                    (now, memory_id, user_id),
                )
                result["deleted"] += cursor.rowcount

            # Update memories
            for memory_id, content, category in to_update:
                cursor = self._execute_with_timing(
                    conn,
                    """
                    UPDATE user_memories
                    SET content = ?, category = ?, updated_at = ?
                    WHERE id = ? AND user_id = ? AND project_id IS NULL AND deleted_at IS NULL
                    """,
                    (content, category, now, memory_id, user_id),
                )
                result["updated"] += cursor.rowcount

            # Add new memories
            for content, category in to_add:
                memory_id = str(uuid.uuid4())
                self._execute_with_timing(
                    conn,
                    """
                    INSERT INTO user_memories (id, user_id, content, category, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (memory_id, user_id, content, category, now, now),
                )
                result["added"] += 1

            conn.commit()

        logger.info(
            "Bulk memory update completed",
            extra={
                "user_id": user_id,
                "deleted": result["deleted"],
                "updated": result["updated"],
                "added": result["added"],
            },
        )

        return result
