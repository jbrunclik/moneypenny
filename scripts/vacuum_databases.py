#!/usr/bin/env python3
"""Database vacuum script for AI Chatbot.

Runs SQLite VACUUM on both the main database (chatbot.db) and blob storage (files.db)
to reclaim space and optimize performance.

Usage:
    python scripts/vacuum_databases.py

This script is designed to be run via systemd timer (weekly) or manually as needed.
"""

import sqlite3
import sys
from pathlib import Path

# Add parent directory to path so we can import from src
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


def vacuum_database(db_path: Path, db_name: str) -> bool:
    """Run VACUUM on a SQLite database.

    Args:
        db_path: Path to the database file
        db_name: Human-readable name for logging

    Returns:
        True if successful, False otherwise
    """
    if not db_path.exists():
        logger.warning(f"{db_name} not found at {db_path}, skipping")
        return True  # Not an error if DB doesn't exist yet

    try:
        # Get size before vacuum
        size_before = db_path.stat().st_size

        logger.info(
            f"Starting VACUUM on {db_name}", extra={"path": str(db_path), "size_bytes": size_before}
        )

        # Connect and run VACUUM
        # VACUUM requires exclusive access and cannot be run inside a transaction
        conn = sqlite3.connect(str(db_path), isolation_level=None)
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()

        # Get size after vacuum
        size_after = db_path.stat().st_size
        size_diff = size_before - size_after
        size_diff_pct = (size_diff / size_before * 100) if size_before > 0 else 0

        logger.info(
            f"VACUUM completed on {db_name}",
            extra={
                "path": str(db_path),
                "size_before_bytes": size_before,
                "size_after_bytes": size_after,
                "reclaimed_bytes": size_diff,
                "reclaimed_pct": round(size_diff_pct, 2),
            },
        )
        return True

    except sqlite3.Error as e:
        logger.error(
            f"VACUUM failed on {db_name}",
            extra={"path": str(db_path), "error": str(e)},
            exc_info=True,
        )
        return False
    except OSError as e:
        logger.error(
            f"File error during VACUUM on {db_name}",
            extra={"path": str(db_path), "error": str(e)},
            exc_info=True,
        )
        return False


def main() -> int:
    """Run VACUUM on all databases.

    Returns:
        0 if all databases vacuumed successfully, 1 if any failed
    """
    logger.info("Starting database vacuum")

    databases = [
        (Config.DATABASE_PATH, "Main database (chatbot.db)"),
        (Config.BLOB_STORAGE_PATH, "Blob storage (files.db)"),
    ]

    all_success = True
    for db_path, db_name in databases:
        if not vacuum_database(db_path, db_name):
            all_success = False

    if all_success:
        logger.info("Database vacuum completed successfully")
        return 0
    else:
        logger.error("Database vacuum completed with errors")
        return 1


if __name__ == "__main__":
    sys.exit(main())
