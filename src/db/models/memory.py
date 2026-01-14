"""Memory database operations mixin.

Contains all methods for UserMemory entity management including:
- CRUD operations
- Bulk updates (for defragmentation)
- User queries with memory counts
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
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

    def add_memory(self, user_id: str, content: str, category: str | None = None) -> Memory:
        """Add a memory for a user.

        Args:
            user_id: The user ID
            content: The memory content
            category: Optional category (preference, fact, context, goal)

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
                """INSERT INTO user_memories (id, user_id, content, category, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (memory_id, user_id, content, category, now.isoformat(), now.isoformat()),
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
                       WHERE id = ? AND user_id = ?""",
                    (content, category, now, memory_id, user_id),
                )
            else:
                cursor = self._execute_with_timing(
                    conn,
                    """UPDATE user_memories SET content = ?, updated_at = ?
                       WHERE id = ? AND user_id = ?""",
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

    def delete_memory(self, memory_id: str, user_id: str) -> bool:
        """Delete a memory.

        Args:
            memory_id: The memory ID
            user_id: The user ID (for ownership verification)

        Returns:
            True if memory was deleted, False if not found
        """
        logger.debug(
            "Deleting memory",
            extra={"user_id": user_id, "memory_id": memory_id},
        )

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM user_memories WHERE id = ? AND user_id = ?",
                (memory_id, user_id),
            )
            conn.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info("Memory deleted", extra={"memory_id": memory_id, "user_id": user_id})
        else:
            logger.warning(
                "Memory not found for deletion",
                extra={"memory_id": memory_id, "user_id": user_id},
            )
        return deleted

    def list_memories(self, user_id: str) -> list[Memory]:
        """List all memories for a user.

        Args:
            user_id: The user ID

        Returns:
            List of Memory objects, ordered by updated_at DESC
        """
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM user_memories WHERE user_id = ?
                   ORDER BY updated_at DESC""",
                (user_id,),
            ).fetchall()

            return [
                Memory(
                    id=row["id"],
                    user_id=row["user_id"],
                    content=row["content"],
                    category=row["category"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
                for row in rows
            ]

    def get_memory_count(self, user_id: str) -> int:
        """Get the count of memories for a user.

        Args:
            user_id: The user ID

        Returns:
            Number of memories
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT COUNT(*) as count FROM user_memories WHERE user_id = ?",
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
                LEFT JOIN user_memories m ON u.id = m.user_id
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

        Args:
            user_id: The user ID
            to_delete: List of memory IDs to delete
            to_update: List of (memory_id, new_content, category) tuples
            to_add: List of (content, category) tuples for new memories

        Returns:
            Dict with counts: {"deleted": N, "updated": N, "added": N}
        """
        now = datetime.utcnow().isoformat()
        result = {"deleted": 0, "updated": 0, "added": 0}

        with self._pool.get_connection() as conn:
            # Delete memories
            for memory_id in to_delete:
                cursor = self._execute_with_timing(
                    conn,
                    "DELETE FROM user_memories WHERE id = ? AND user_id = ?",
                    (memory_id, user_id),
                )
                result["deleted"] += cursor.rowcount

            # Update memories
            for memory_id, content, category in to_update:
                cursor = self._execute_with_timing(
                    conn,
                    """
                    UPDATE user_memories
                    SET content = ?, category = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
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
