"""Shared helper functions for database operations.

This module contains utility functions used across multiple database modules:
- Blob storage helpers (file upload/download)
- Cursor-based pagination helpers
- Planner reset logic
- Database connectivity checks
"""

from __future__ import annotations

import base64
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.db.blob_store import get_blob_store
from src.utils.clock import planner_cutoff, utc_now
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.db.models.dataclasses import User

logger = get_logger(__name__)


# ============================================================================
# Blob Storage Helpers
# ============================================================================


def make_blob_key(message_id: str, file_index: int) -> str:
    """Create blob key for a file."""
    return f"{message_id}/{file_index}"


def make_thumbnail_key(message_id: str, file_index: int) -> str:
    """Create blob key for a thumbnail."""
    return f"{message_id}/{file_index}.thumb"


def save_file_to_blob_store(message_id: str, file_index: int, file_data: dict[str, Any]) -> None:
    """Save file data and thumbnail to blob store.

    Args:
        message_id: Message ID
        file_index: Index of file in message's files array
        file_data: File dict containing 'data', 'type', and optionally 'thumbnail'
    """
    blob_store = get_blob_store()
    mime_type = file_data.get("type", "application/octet-stream")

    # Save main file data
    if "data" in file_data:
        try:
            data_bytes = base64.b64decode(file_data["data"])
            blob_store.save(make_blob_key(message_id, file_index), data_bytes, mime_type)
        except Exception:
            logger.exception(
                "Failed to save file to blob store",
                extra={"message_id": message_id, "file_index": file_index},
            )

    # Save thumbnail if present
    if file_data.get("thumbnail"):
        try:
            thumb_bytes = base64.b64decode(file_data["thumbnail"])
            # Thumbnails are always JPEG
            blob_store.save(make_thumbnail_key(message_id, file_index), thumb_bytes, "image/jpeg")
        except Exception:
            logger.exception(
                "Failed to save thumbnail to blob store",
                extra={"message_id": message_id, "file_index": file_index},
            )


def extract_file_metadata(file_data: dict[str, Any]) -> dict[str, Any]:
    """Extract metadata from file dict, removing binary data.

    Returns a new dict with 'data' and 'thumbnail' removed, plus 'size' added.
    """
    # Copy over non-data fields
    metadata = {key: value for key, value in file_data.items() if key not in ("data", "thumbnail")}

    # Calculate and store size from data
    if "data" in file_data:
        try:
            data_bytes = base64.b64decode(file_data["data"])
            metadata["size"] = len(data_bytes)
        except ValueError, TypeError:
            metadata["size"] = 0

    # Track whether thumbnail exists
    metadata["has_thumbnail"] = bool(file_data.get("thumbnail"))

    return metadata


def delete_message_blobs(message_id: str) -> int:
    """Delete all blobs for a message."""
    blob_store = get_blob_store()
    return blob_store.delete_by_prefix(f"{message_id}/")


def delete_messages_blobs(message_ids: list[str]) -> int:
    """Delete all blobs for multiple messages in a single query.

    More efficient than calling delete_message_blobs() in a loop.
    """
    if not message_ids:
        return 0
    blob_store = get_blob_store()
    prefixes = [f"{msg_id}/" for msg_id in message_ids]
    return blob_store.delete_by_prefixes(prefixes)


# ============================================================================
# Cursor-Based Pagination Helpers
# ============================================================================


def build_cursor(timestamp: str, id: str) -> str:
    """Build a cursor string from timestamp and id.

    Format: '{timestamp}:{id}'
    The id serves as a tie-breaker for items with the same timestamp.
    """
    return f"{timestamp}:{id}"


def parse_cursor(cursor: str) -> tuple[str, str]:
    """Parse a cursor string into (timestamp, id).

    Args:
        cursor: Cursor string in format '{timestamp}:{id}'

    Returns:
        Tuple of (timestamp, id)

    Raises:
        ValueError: If cursor format is invalid
    """
    # Use rsplit with maxsplit=1 to handle timestamps that contain colons
    parts = cursor.rsplit(":", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid cursor format: {cursor}")
    return parts[0], parts[1]


# ============================================================================
# Planner Helpers
# ============================================================================


def should_reset_planner(user: User, now: datetime | None = None) -> bool:
    """Check if the planner should be automatically reset.

    The planner resets daily at 4am local time (APP_TIMEZONE). This function
    checks if the last reset was before the most recent 4am.

    Args:
        user: The User object with planner_last_reset_at field
        now: The current instant, aware (defaults to now)

    Returns:
        True if the planner should be reset, False otherwise
    """
    # If never reset before, this is first use - don't auto-reset
    if not user.planner_last_reset_at:
        return False

    return user.planner_last_reset_at < planner_cutoff(now or utc_now())


def check_database_connectivity(db_path: Path | None = None) -> tuple[bool, str | None]:
    """Check if the database is accessible.

    This function performs a series of checks to verify database connectivity
    before starting the application. It checks directory existence, permissions,
    and performs a simple query test.

    Args:
        db_path: Optional path to database file. Uses Config.DATABASE_PATH if not provided.

    Returns:
        Tuple of (success: bool, error_message: str | None)
    """
    db_path = db_path or Config.DATABASE_PATH
    logger.debug("Checking database connectivity", extra={"db_path": str(db_path)})

    # Check if parent directory exists and is writable
    parent_dir = db_path.parent
    if not parent_dir.exists():
        error = f"Database directory does not exist: {parent_dir}"
        logger.error("Database connectivity check failed", extra={"error": error})
        return False, error

    if not os.access(parent_dir, os.W_OK):
        error = f"Database directory is not writable: {parent_dir}"
        logger.error("Database connectivity check failed", extra={"error": error})
        return False, error

    # Check if database file exists and is accessible
    if db_path.exists() and not os.access(db_path, os.R_OK | os.W_OK):
        error = f"Database file is not readable/writable: {db_path}"
        logger.error("Database connectivity check failed", extra={"error": error})
        return False, error

    # Try to connect and run a simple query
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT 1")
        conn.close()
        logger.debug("Database connectivity check passed", extra={"db_path": str(db_path)})
        return True, None
    except sqlite3.OperationalError as e:
        error_msg = str(e)
        if "unable to open database file" in error_msg:
            error = f"Cannot open database file: {db_path}. Check file permissions."
        elif "database is locked" in error_msg:
            error = f"Database is locked: {db_path}. Another process may be using it."
        elif "disk I/O error" in error_msg:
            error = f"Disk I/O error accessing database: {db_path}. Check disk health."
        else:
            error = f"Database error: {error_msg}"
        logger.error("Database connectivity check failed", extra={"error": error})  # noqa: TRY400 - classified; the message names the cause
        return False, error
    except Exception as e:
        error = f"Unexpected database error: {e}"
        logger.exception("Database connectivity check failed", extra={"error": error})
        return False, error


def check_database_writable(
    db_path: Path | None = None, timeout_s: float | None = None
) -> tuple[bool, str | None]:
    """Check that a write could take the database's write lock.

    A connection that writes and never commits keeps the write lock: every
    other write then fails with "database is locked" while reads still pass
    (Oct 25 2026). Takes the lock and releases it at once, writing nothing.

    Returns:
        Tuple of (success: bool, error_message: str | None)
    """
    db_path = db_path or Config.DATABASE_PATH
    timeout_s = Config.READY_WRITE_LOCK_TIMEOUT_SECONDS if timeout_s is None else timeout_s
    try:
        conn = sqlite3.connect(db_path, timeout=timeout_s)
    except sqlite3.Error as e:
        return False, f"Database error: {e}"
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.rollback()
    except sqlite3.OperationalError as e:
        if "database is locked" not in str(e):
            return False, f"Database error: {e}"
        error = f"Database write lock is held for over {timeout_s:g}s: writes are failing"
        logger.error("Database write check failed", extra={"error": error})  # noqa: TRY400 - lock contention; a traceback adds nothing
        return False, error
    finally:
        conn.close()
    return True, None
