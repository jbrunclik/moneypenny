"""Memory database operations mixin.

Contains all methods for UserMemory entity management including:
- CRUD operations
- Bulk updates (for defragmentation)
- User queries with memory counts
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.db.models.dataclasses import Memory, User
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


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
        now = datetime.now()
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
                    now.isoformat(),
                    now.isoformat(),
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

    def update_memory(
        self, memory_id: str, user_id: str, content: str, category: str | None = None
    ) -> bool:
        """Update a memory's content.

        Args:
            memory_id: The memory ID
            user_id: The user ID (for ownership verification)
            content: New content
            category: Optional new category

        Returns:
            True if memory was updated, False if not found
        """
        now = datetime.now().isoformat()
        logger.debug(
            "Updating memory",
            extra={"user_id": user_id, "memory_id": memory_id},
        )

        with self._pool.get_connection() as conn:
            if category is not None:
                cursor = self._execute_with_timing(
                    conn,
                    """UPDATE user_memories SET content = ?, category = ?, updated_at = ?
                       WHERE id = ? AND user_id = ? AND deleted_at IS NULL""",
                    (content, category, now, memory_id, user_id),
                )
            else:
                cursor = self._execute_with_timing(
                    conn,
                    """UPDATE user_memories SET content = ?, updated_at = ?
                       WHERE id = ? AND user_id = ? AND deleted_at IS NULL""",
                    (content, now, memory_id, user_id),
                )
            conn.commit()
            updated = cursor.rowcount > 0

        if updated:
            logger.info("Memory updated", extra={"memory_id": memory_id, "user_id": user_id})
        else:
            logger.warning(
                "Memory not found for update",
                extra={"memory_id": memory_id, "user_id": user_id},
            )
        return updated

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
                """UPDATE user_memories SET protected = ?
                   WHERE id = ? AND user_id = ? AND deleted_at IS NULL""",
                (int(protected), memory_id, user_id),
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

        query = """UPDATE user_memories SET deleted_at = ?
                   WHERE id = ? AND user_id = ? AND deleted_at IS NULL"""
        if not allow_protected:
            query += " AND protected = 0"

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                query,
                (datetime.now().isoformat(), memory_id, user_id),
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
        """Undo a soft delete, provided the row has not been purged yet.

        Args:
            memory_id: The memory ID
            user_id: The user ID (for ownership verification)

        Returns:
            True if memory was restored, False if not found or not deleted
        """
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE user_memories SET deleted_at = NULL
                   WHERE id = ? AND user_id = ? AND deleted_at IS NOT NULL""",
                (memory_id, user_id),
            )
            conn.commit()
            restored = cursor.rowcount > 0

        if restored:
            logger.info("Memory restored", extra={"memory_id": memory_id, "user_id": user_id})
        return restored

    def purge_deleted_memories(self, retention_days: int) -> int:
        """Hard-delete soft-deleted memories past the retention window.

        Args:
            retention_days: Days to retain soft-deleted rows

        Returns:
            Number of rows purged
        """
        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM user_memories WHERE deleted_at IS NOT NULL AND deleted_at < ?",
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
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            protected=bool(row["protected"]),
            source_conversation_id=row["source_conversation_id"],
            deleted_at=(datetime.fromisoformat(row["deleted_at"]) if row["deleted_at"] else None),
        )

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
                """SELECT * FROM user_memories
                   WHERE id = ? AND user_id = ? AND deleted_at IS NULL""",
                (memory_id, user_id),
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
                """SELECT * FROM user_memories WHERE user_id = ? AND deleted_at IS NULL
                   ORDER BY updated_at DESC""",
                (user_id,),
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
                """SELECT * FROM user_memories WHERE user_id = ? AND deleted_at IS NOT NULL
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
                """SELECT COUNT(*) as count FROM user_memories
                   WHERE user_id = ? AND deleted_at IS NULL""",
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
                  ON u.id = m.user_id AND m.deleted_at IS NULL
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
                        created_at=datetime.fromisoformat(row["created_at"]),
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
        # Local-naive, matching add_memory/update_memory and the user-facing
        # convention in src/utils/datetime_utils.py. Using utcnow() here stamped
        # defragged memories behind their own created_at by the UTC offset.
        now = datetime.now().isoformat()
        result = {"deleted": 0, "updated": 0, "added": 0}

        with self._pool.get_connection() as conn:
            # Soft-delete memories, skipping protected ones
            for memory_id in to_delete:
                cursor = self._execute_with_timing(
                    conn,
                    """
                    UPDATE user_memories SET deleted_at = ?
                    WHERE id = ? AND user_id = ? AND deleted_at IS NULL AND protected = 0
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
                    WHERE id = ? AND user_id = ? AND deleted_at IS NULL
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
