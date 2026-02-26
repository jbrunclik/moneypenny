"""Key-value store database operations mixin.

Contains methods for per-user, namespaced key-value storage.
Used by autonomous agents and features that need persistent storage.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class KVStoreMixin:
    """Mixin providing key-value store database operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def kv_get(self, user_id: str, namespace: str, key: str) -> str | None:
        """Get a value by key.

        Args:
            user_id: The user's ID
            namespace: The namespace (e.g., 'agent:my-agent', 'news')
            key: The key to look up

        Returns:
            The value, or None if not found
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT value FROM kv_store WHERE user_id = ? AND namespace = ? AND key = ?",
                (user_id, namespace, key),
            ).fetchone()
            return row["value"] if row else None

    def kv_set(self, user_id: str, namespace: str, key: str, value: str) -> None:
        """Set a key-value pair (upsert).

        Args:
            user_id: The user's ID
            namespace: The namespace
            key: The key
            value: The value (string, use JSON for complex data)
        """
        now = datetime.utcnow().isoformat()
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """
                INSERT INTO kv_store (user_id, namespace, key, value, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, namespace, key)
                DO UPDATE SET value = ?, updated_at = ?
                """,
                (user_id, namespace, key, value, now, now, value, now),
            )
            conn.commit()

    def kv_delete(self, user_id: str, namespace: str, key: str) -> bool:
        """Delete a key.

        Args:
            user_id: The user's ID
            namespace: The namespace
            key: The key to delete

        Returns:
            True if the key existed and was deleted
        """
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM kv_store WHERE user_id = ? AND namespace = ? AND key = ?",
                (user_id, namespace, key),
            )
            conn.commit()
            return cursor.rowcount > 0

    def kv_list(
        self, user_id: str, namespace: str, prefix: str | None = None
    ) -> list[tuple[str, str]]:
        """List key-value pairs in a namespace.

        Args:
            user_id: The user's ID
            namespace: The namespace
            prefix: Optional key prefix filter

        Returns:
            List of (key, value) tuples
        """
        with self._pool.get_connection() as conn:
            if prefix:
                rows = self._execute_with_timing(
                    conn,
                    "SELECT key, value FROM kv_store WHERE user_id = ? AND namespace = ? AND key LIKE ? ORDER BY key",
                    (user_id, namespace, f"{prefix}%"),
                ).fetchall()
            else:
                rows = self._execute_with_timing(
                    conn,
                    "SELECT key, value FROM kv_store WHERE user_id = ? AND namespace = ? ORDER BY key",
                    (user_id, namespace),
                ).fetchall()
            return [(row["key"], row["value"]) for row in rows]

    def kv_count(self, user_id: str, namespace: str) -> int:
        """Count keys in a namespace.

        Args:
            user_id: The user's ID
            namespace: The namespace

        Returns:
            Number of keys
        """
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT COUNT(*) as cnt FROM kv_store WHERE user_id = ? AND namespace = ?",
                (user_id, namespace),
            ).fetchone()
            return row["cnt"] if row else 0

    def kv_list_namespaces(self, user_id: str) -> list[tuple[str, int]]:
        """List all namespaces with key counts for a user.

        Args:
            user_id: The user's ID

        Returns:
            List of (namespace, key_count) tuples
        """
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                "SELECT namespace, COUNT(*) as cnt FROM kv_store WHERE user_id = ? GROUP BY namespace ORDER BY namespace",
                (user_id,),
            ).fetchall()
            return [(row["namespace"], row["cnt"]) for row in rows]

    def kv_clear_namespace(self, user_id: str, namespace: str) -> int:
        """Delete all keys in a namespace.

        Args:
            user_id: The user's ID
            namespace: The namespace to clear

        Returns:
            Number of keys deleted
        """
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM kv_store WHERE user_id = ? AND namespace = ?",
                (user_id, namespace),
            )
            conn.commit()
            return cursor.rowcount

    def kv_clear_user(self, user_id: str) -> int:
        """Delete all keys for a user across all namespaces.

        Args:
            user_id: The user's ID

        Returns:
            Number of keys deleted
        """
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM kv_store WHERE user_id = ?",
                (user_id,),
            )
            conn.commit()
            return cursor.rowcount
