#!/usr/bin/env python3
"""Checkpoint cleanup script for AI Chatbot.

Deletes LangGraph checkpoint data older than CHECKPOINT_TTL_MINUTES (default: 30)
to prevent unbounded database growth. Checkpoints are only needed for in-flight
agent requests, so short retention is safe.

Usage:
    python scripts/cleanup_checkpoints.py
    python scripts/cleanup_checkpoints.py --dry-run

This script is designed to be run via systemd timer or manually as needed.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

# Add parent directory to path so we can import from src
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


def cleanup_checkpoints(db_path: Path, ttl_minutes: int, *, dry_run: bool = False) -> int:
    """Delete checkpoint and write records older than ttl_minutes.

    The checkpoints table has no timestamp column, but checkpoint_id is a
    UUID-v6-like string that sorts chronologically. Instead of parsing it,
    we add a created_at column (defaulting to CURRENT_TIMESTAMP) and filter
    on that.

    Args:
        db_path: Path to the checkpoints.db file
        ttl_minutes: Delete records older than this many minutes
        dry_run: If True, only report what would be deleted

    Returns:
        Number of checkpoint rows deleted (0 if dry_run)
    """
    if not db_path.exists():
        logger.info(
            "Checkpoints database not found, nothing to clean up", extra={"path": str(db_path)}
        )
        return 0

    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        # Ensure created_at column exists (idempotent)
        _ensure_created_at_column(conn)

        # Count rows that would be deleted
        # NULL created_at means pre-existing rows from before the column was added — treat as expired
        cutoff_sql = f"datetime('now', '-{ttl_minutes} minutes')"
        expired_where = f"created_at IS NULL OR created_at < {cutoff_sql}"

        row = conn.execute(f"SELECT COUNT(*) FROM checkpoints WHERE {expired_where}").fetchone()
        expired_checkpoints = row[0] if row else 0

        row = conn.execute(f"SELECT COUNT(*) FROM writes WHERE {expired_where}").fetchone()
        expired_writes = row[0] if row else 0

        row = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()
        total_checkpoints = row[0] if row else 0

        row = conn.execute("SELECT COUNT(*) FROM writes").fetchone()
        total_writes = row[0] if row else 0

        logger.info(
            "Checkpoint cleanup stats",
            extra={
                "total_checkpoints": total_checkpoints,
                "total_writes": total_writes,
                "expired_checkpoints": expired_checkpoints,
                "expired_writes": expired_writes,
                "ttl_minutes": ttl_minutes,
                "dry_run": dry_run,
            },
        )

        if dry_run:
            logger.info("Dry run: no rows deleted")
            return 0

        if expired_checkpoints == 0 and expired_writes == 0:
            logger.info("No expired checkpoints to clean up")
            return 0

        # Delete expired rows (writes first due to logical dependency)
        conn.execute(f"DELETE FROM writes WHERE {expired_where}")
        conn.execute(f"DELETE FROM checkpoints WHERE {expired_where}")

        logger.info(
            "Checkpoint cleanup completed",
            extra={
                "deleted_checkpoints": expired_checkpoints,
                "deleted_writes": expired_writes,
            },
        )
        return expired_checkpoints

    except sqlite3.Error as e:
        logger.error("Checkpoint cleanup failed", extra={"error": str(e)}, exc_info=True)
        return 0
    finally:
        conn.close()


def _ensure_created_at_column(conn: sqlite3.Connection) -> None:
    """Add created_at column to checkpoints and writes tables if missing.

    SQLite ALTER TABLE doesn't allow CURRENT_TIMESTAMP as a default, so we
    add the column with no default and use an INSERT trigger to set it.
    """
    for table in ("checkpoints", "writes"):
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if "created_at" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN created_at TIMESTAMP")
            conn.execute(
                f"""CREATE TRIGGER IF NOT EXISTS {table}_set_created_at
                    AFTER INSERT ON {table}
                    FOR EACH ROW
                    WHEN NEW.created_at IS NULL
                    BEGIN
                        UPDATE {table} SET created_at = CURRENT_TIMESTAMP
                        WHERE rowid = NEW.rowid;
                    END"""
            )
            logger.info(f"Added created_at column and trigger to {table} table")


def main() -> int:
    """Run checkpoint cleanup.

    Returns:
        0 on success, 1 on error
    """
    parser = argparse.ArgumentParser(description="Clean up expired LangGraph checkpoints")
    parser.add_argument("--dry-run", action="store_true", help="Only report what would be deleted")
    args = parser.parse_args()

    logger.info(
        "Starting checkpoint cleanup",
        extra={
            "ttl_minutes": Config.CHECKPOINT_TTL_MINUTES,
            "db_path": str(Config.CHECKPOINT_DB_PATH),
        },
    )

    try:
        deleted = cleanup_checkpoints(
            Config.CHECKPOINT_DB_PATH,
            Config.CHECKPOINT_TTL_MINUTES,
            dry_run=args.dry_run,
        )
        logger.info("Checkpoint cleanup finished", extra={"deleted": deleted})
        return 0
    except Exception as e:
        logger.error("Checkpoint cleanup failed", extra={"error": str(e)}, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
