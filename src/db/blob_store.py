"""Blob storage for files and thumbnails.

This module provides a SQLite-based blob storage for file data and thumbnails,
separate from the main chatbot database. Using native BLOB storage instead of
base64-encoded JSON reduces storage size by ~33% and improves query performance.

Key format:
- Files: "{message_id}/{index}" (e.g., "abc123/0")
- Thumbnails: "{message_id}/{index}.thumb" (e.g., "abc123/0.thumb")
"""

import sqlite3
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


class BlobStore:
    """SQLite-based blob storage for files and thumbnails."""

    def __init__(self, db_path: Path | None = None) -> None:
        """Initialize blob store.

        Args:
            db_path: Path to the blob database file. Uses Config.BLOB_STORAGE_PATH if not provided.
        """
        self.db_path = db_path or Config.BLOB_STORAGE_PATH
        self._should_log_queries = Config.LOG_LEVEL == "DEBUG" or Config.is_development()
        self._slow_query_threshold_ms = Config.SLOW_QUERY_THRESHOLD_MS
        self._init_db()

    @contextmanager
    def _get_conn(self) -> Generator[sqlite3.Connection]:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[object, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute a query with optional timing and logging."""
        if not self._should_log_queries:
            return conn.execute(query, params)

        start_time = time.perf_counter()
        cursor = conn.execute(query, params)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Truncate query for logging
        query_snippet = " ".join(query.split())
        if len(query_snippet) > 200:
            query_snippet = query_snippet[:200] + "..."

        if elapsed_ms >= self._slow_query_threshold_ms:
            logger.warning(
                "Slow blob query detected",
                extra={
                    "query_snippet": query_snippet,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "threshold_ms": self._slow_query_threshold_ms,
                },
            )
        elif Config.LOG_LEVEL == "DEBUG":
            logger.debug(
                "Blob query executed",
                extra={
                    "query_snippet": query_snippet,
                    "elapsed_ms": round(elapsed_ms, 2),
                },
            )

        return cursor

    def _init_db(self) -> None:
        """Initialize the blob database schema."""
        logger.debug("Initializing blob store", extra={"db_path": str(self.db_path)})
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS blobs (
                    key TEXT PRIMARY KEY,
                    data BLOB NOT NULL,
                    mime_type TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            # Index for prefix-based queries (e.g., delete all blobs for a message)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_blobs_key_prefix
                ON blobs(key)
            """)
            conn.commit()

    def save(self, key: str, data: bytes, mime_type: str) -> None:
        """Save a blob to the store.

        Args:
            key: Unique key for the blob (e.g., "{message_id}/{index}")
            data: Binary data to store
            mime_type: MIME type of the data
        """
        logger.debug(
            "Saving blob",
            extra={"key": key, "size": len(data), "mime_type": mime_type},
        )
        with self._get_conn() as conn:
            self._execute_with_timing(
                conn,
                """INSERT OR REPLACE INTO blobs (key, data, mime_type, size, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, data, mime_type, len(data), datetime.now().isoformat()),
            )
            conn.commit()

    def get(self, key: str) -> tuple[bytes, str] | None:
        """Retrieve a blob from the store.

        Args:
            key: The blob key

        Returns:
            Tuple of (data, mime_type) if found, None otherwise
        """
        with self._get_conn() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT data, mime_type FROM blobs WHERE key = ?",
                (key,),
            ).fetchone()

            if not row:
                return None

            return bytes(row["data"]), row["mime_type"]

    def delete(self, key: str) -> bool:
        """Delete a blob from the store.

        Args:
            key: The blob key

        Returns:
            True if deleted, False if not found
        """
        logger.debug("Deleting blob", extra={"key": key})
        with self._get_conn() as conn:
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM blobs WHERE key = ?",
                (key,),
            )
            conn.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            logger.debug("Blob deleted", extra={"key": key})
        return deleted

    def delete_by_prefix(self, prefix: str) -> int:
        """Delete all blobs with keys starting with the given prefix.

        Useful for deleting all files associated with a message.

        Args:
            prefix: Key prefix to match (e.g., "{message_id}/")

        Returns:
            Number of blobs deleted
        """
        logger.debug("Deleting blobs by prefix", extra={"prefix": prefix})
        with self._get_conn() as conn:
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM blobs WHERE key LIKE ?",
                (prefix + "%",),
            )
            conn.commit()
            count = cursor.rowcount

        logger.debug("Blobs deleted by prefix", extra={"prefix": prefix, "count": count})
        return count

    def exists(self, key: str) -> bool:
        """Check if a blob exists.

        Args:
            key: The blob key

        Returns:
            True if exists, False otherwise
        """
        with self._get_conn() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT 1 FROM blobs WHERE key = ?",
                (key,),
            ).fetchone()
            return row is not None

    def get_size(self, key: str) -> int | None:
        """Get the size of a blob without loading the data.

        Args:
            key: The blob key

        Returns:
            Size in bytes if found, None otherwise
        """
        with self._get_conn() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT size FROM blobs WHERE key = ?",
                (key,),
            ).fetchone()
            return row["size"] if row else None


# Global blob store instance (lazy initialization)
_blob_store: BlobStore | None = None


def get_blob_store() -> BlobStore:
    """Get the global blob store instance."""
    global _blob_store
    if _blob_store is None:
        _blob_store = BlobStore()
    return _blob_store


def reset_blob_store() -> None:
    """Reset the global blob store instance (for testing)."""
    global _blob_store
    _blob_store = None
