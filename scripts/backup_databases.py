#!/usr/bin/env python3
"""Database backup script for AI Chatbot.

Creates timestamped snapshots of both SQLite databases (chatbot.db and files.db),
keeping a configurable number of backups (default: 7 days of history).

Usage:
    python scripts/backup_databases.py [--retention DAYS]

This script is designed to be run via systemd timer (daily) or manually as needed.
"""

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add parent directory to path so we can import from src
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Default backup retention in days
DEFAULT_RETENTION_DAYS = 7

# Backup directory relative to database location
BACKUP_DIR_NAME = "backups"


def get_backup_dir(db_path: Path) -> Path:
    """Get the backup directory for a database.

    Creates directory structure: {db_parent}/backups/{db_name}/
    Example: ./backups/chatbot.db/ for ./chatbot.db

    Args:
        db_path: Path to the database file

    Returns:
        Path to the backup directory
    """
    return db_path.parent / BACKUP_DIR_NAME / db_path.name


def create_backup(db_path: Path, db_name: str) -> bool:
    """Create a backup of a SQLite database using online backup API.

    Uses SQLite's backup API to create a consistent snapshot even while
    the database is in use.

    Args:
        db_path: Path to the database file
        db_name: Human-readable name for logging

    Returns:
        True if successful, False otherwise
    """
    if not db_path.exists():
        logger.warning(f"{db_name} not found at {db_path}, skipping backup")
        return True  # Not an error if DB doesn't exist yet

    backup_dir = get_backup_dir(db_path)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}-{timestamp}.db"

    try:
        # Ensure backup directory exists
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Get source database size for logging
        source_size = db_path.stat().st_size

        logger.info(
            f"Starting backup of {db_name}",
            extra={
                "source": str(db_path),
                "destination": str(backup_path),
                "source_size_bytes": source_size,
            },
        )

        # Use SQLite's online backup API for consistent snapshot
        # This works even if the database is being written to
        source_conn = sqlite3.connect(str(db_path))
        try:
            backup_conn = sqlite3.connect(str(backup_path))
            try:
                source_conn.backup(backup_conn)
            finally:
                backup_conn.close()
        finally:
            source_conn.close()

        # Verify backup was created and has reasonable size
        backup_size = backup_path.stat().st_size
        if backup_size == 0:
            logger.error(
                f"Backup file is empty for {db_name}",
                extra={"backup_path": str(backup_path)},
            )
            backup_path.unlink()  # Remove empty backup
            return False

        logger.info(
            f"Backup completed for {db_name}",
            extra={
                "backup_path": str(backup_path),
                "backup_size_bytes": backup_size,
            },
        )
        return True

    except sqlite3.Error as e:
        logger.error(
            f"SQLite error during backup of {db_name}",
            extra={"path": str(db_path), "error": str(e)},
            exc_info=True,
        )
        # Clean up partial backup if it exists
        if backup_path.exists():
            backup_path.unlink()
        return False
    except OSError as e:
        logger.error(
            f"File error during backup of {db_name}",
            extra={"path": str(db_path), "error": str(e)},
            exc_info=True,
        )
        return False


def cleanup_old_backups(db_path: Path, db_name: str, retention_days: int) -> int:
    """Remove backups older than retention period.

    Args:
        db_path: Path to the database file
        db_name: Human-readable name for logging
        retention_days: Number of days to keep backups

    Returns:
        Number of backups removed
    """
    backup_dir = get_backup_dir(db_path)
    if not backup_dir.exists():
        return 0

    removed_count = 0
    now = datetime.now(UTC)

    # Find all backup files matching pattern: {stem}-YYYYMMDD-HHMMSS.db
    for backup_file in backup_dir.glob(f"{db_path.stem}-*.db"):
        try:
            # Extract timestamp from filename
            # Format: chatbot-20240101-120000.db -> 20240101-120000
            timestamp_str = backup_file.stem.replace(f"{db_path.stem}-", "")
            backup_time = datetime.strptime(timestamp_str, "%Y%m%d-%H%M%S").replace(tzinfo=UTC)

            age_days = (now - backup_time).days
            if age_days > retention_days:
                backup_file.unlink()
                removed_count += 1
                logger.debug(
                    "Removed old backup",
                    extra={
                        "file": str(backup_file),
                        "age_days": age_days,
                    },
                )
        except (ValueError, OSError) as e:
            # Skip files that don't match expected pattern or can't be deleted
            logger.warning(
                "Could not process backup file",
                extra={"file": str(backup_file), "error": str(e)},
            )
            continue

    if removed_count > 0:
        logger.info(
            f"Cleaned up old backups for {db_name}",
            extra={"removed_count": removed_count, "retention_days": retention_days},
        )

    return removed_count


def list_backups(db_path: Path) -> list[tuple[Path, int, datetime]]:
    """List existing backups for a database.

    Args:
        db_path: Path to the database file

    Returns:
        List of (path, size_bytes, timestamp) tuples, newest first
    """
    backup_dir = get_backup_dir(db_path)
    if not backup_dir.exists():
        return []

    backups = []
    for backup_file in backup_dir.glob(f"{db_path.stem}-*.db"):
        try:
            timestamp_str = backup_file.stem.replace(f"{db_path.stem}-", "")
            backup_time = datetime.strptime(timestamp_str, "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
            size = backup_file.stat().st_size
            backups.append((backup_file, size, backup_time))
        except (ValueError, OSError):
            continue

    # Sort by timestamp, newest first
    backups.sort(key=lambda x: x[2], reverse=True)
    return backups


def main() -> int:
    """Run backup on all databases.

    Returns:
        0 if all backups successful, 1 if any failed
    """
    parser = argparse.ArgumentParser(description="Backup AI Chatbot databases")
    parser.add_argument(
        "--retention",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help=f"Number of days to keep backups (default: {DEFAULT_RETENTION_DAYS})",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List existing backups without creating new ones",
    )
    args = parser.parse_args()

    databases = [
        (Config.DATABASE_PATH, "Main database (chatbot.db)"),
        (Config.BLOB_STORAGE_PATH, "Blob storage (files.db)"),
    ]

    # List mode - just show existing backups
    if args.list:
        for db_path, db_name in databases:
            backups = list_backups(db_path)
            print(f"\n{db_name}:")
            if not backups:
                print("  No backups found")
            else:
                for path, size, timestamp in backups:
                    size_mb = size / (1024 * 1024)
                    age_days = (datetime.now(UTC) - timestamp).days
                    print(f"  {path.name}: {size_mb:.1f} MB, {age_days} days old")
        return 0

    # Backup mode
    logger.info(
        "Starting database backup",
        extra={"retention_days": args.retention},
    )

    all_success = True

    for db_path, db_name in databases:
        # Create backup
        if not create_backup(db_path, db_name):
            all_success = False
            continue

        # Cleanup old backups
        cleanup_old_backups(db_path, db_name, args.retention)

    if all_success:
        logger.info("Database backup completed successfully")
        return 0
    else:
        logger.error("Database backup completed with errors")
        return 1


if __name__ == "__main__":
    sys.exit(main())
