#!/usr/bin/env python3
"""Database backup script for Moneypenny.

Creates timestamped snapshots of both SQLite databases (chatbot.db and files.db),
stored zstd-compressed (`<stem>-<timestamp>.db.zst`), keeping a configurable
number of backups (default: 1 day of history).

Usage:
    python scripts/backup_databases.py [--retention DAYS]
    python scripts/backup_databases.py --list
    python scripts/backup_databases.py --decompress PATH.db.zst

This script is designed to be run via systemd timer (daily) or manually as needed.
"""

import argparse
import hashlib
import shutil
import sqlite3
import sys
import time
from compression import zstd
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Add parent directory to path so we can import from src
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Default backup retention in days. Short on purpose: the production host's
# daily full-disk images keep a week of these consistent copies, so a longer
# local history only duplicates them (~1.1 GB uncompressed per day of history).
DEFAULT_RETENTION_DAYS = 1

# Backup directory relative to database location
BACKUP_DIR_NAME = "backups"

# A plain SQLite copy, and its zstd-compressed form (the one kept)
PLAIN_SUFFIX = ".db"
COMPRESSED_SUFFIX = ".db.zst"
BACKUP_SUFFIXES = (COMPRESSED_SUFFIX, PLAIN_SUFFIX)
TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"

# zstd's default level: fast, and higher levels barely shrink SQLite pages more
ZSTD_LEVEL = 3
COPY_CHUNK_BYTES = 1024 * 1024


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


def _sha256(stream: Any) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(COPY_CHUNK_BYTES):
        digest.update(chunk)
    return digest.hexdigest()


def _compress(plain: Path) -> Path:
    """Compress a plain backup next to itself and verify it round-trips.

    Writes `<name>.db.zst` through a `.tmp` file, checks the decompressed bytes
    hash the same as the plain copy, then removes the plain copy. On any
    failure the plain copy stays and the partial file is removed.
    """
    compressed = plain.with_name(plain.name.removesuffix(PLAIN_SUFFIX) + COMPRESSED_SUFFIX)
    partial = compressed.with_name(compressed.name + ".tmp")
    try:
        with plain.open("rb") as source, zstd.open(partial, "wb", level=ZSTD_LEVEL) as target:
            shutil.copyfileobj(source, target, COPY_CHUNK_BYTES)
        with plain.open("rb") as source, zstd.open(partial, "rb") as check:
            if _sha256(source) != _sha256(check):
                raise ValueError("compressed backup does not match the plain copy")
        partial.replace(compressed)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    plain.unlink()
    return compressed


def decompress_backup(compressed: Path) -> Path:
    """Decompress a `.db.zst` backup next to itself and check its integrity.

    Returns the plain `.db` path. Refuses to overwrite an existing file and
    raises ValueError (leaving nothing behind) for a corrupt or non-SQLite file.
    """
    target = compressed.with_suffix("")
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    try:
        with zstd.open(compressed, "rb") as source, target.open("xb") as out:
            shutil.copyfileobj(source, out, COPY_CHUNK_BYTES)
        conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
        if result != "ok":
            raise ValueError(f"integrity_check: {result}")
    except (zstd.ZstdError, sqlite3.DatabaseError, EOFError) as e:
        target.unlink(missing_ok=True)
        raise ValueError(f"{compressed} is not a valid backup: {e}") from e
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def _compress_logged(plain: Path, db_name: str) -> None:
    """Compress a finished backup; a failure keeps the plain copy (still a backup)."""
    plain_size = plain.stat().st_size
    started = time.monotonic()
    try:
        compressed = _compress(plain)
    except (OSError, ValueError, zstd.ZstdError) as e:
        logger.exception(
            "Backup compression failed, kept the uncompressed copy",
            extra={"database": db_name, "backup_path": str(plain), "error": str(e)},
        )
        return
    compressed_size = compressed.stat().st_size
    logger.info(
        "Backup compressed",
        extra={
            "database": db_name,
            "backup_path": str(compressed),
            "plain_size_bytes": plain_size,
            "compressed_size_bytes": compressed_size,
            "ratio": round(compressed_size / plain_size, 3) if plain_size else None,
            "duration_ms": round((time.monotonic() - started) * 1000),
        },
    )


def create_backup(db_path: Path, db_name: str) -> bool:
    """Create a backup of a SQLite database using online backup API.

    Uses SQLite's backup API to create a consistent snapshot even while
    the database is in use, then compresses it (`_compress_logged`).

    Args:
        db_path: Path to the database file
        db_name: Human-readable name for logging

    Returns:
        True if successful, False otherwise
    """
    if not db_path.exists():
        logger.warning(
            "Database not found, skipping backup",
            extra={"database": db_name, "path": str(db_path)},
        )
        return True  # Not an error if DB doesn't exist yet

    backup_dir = get_backup_dir(db_path)
    timestamp = datetime.now(UTC).strftime(TIMESTAMP_FORMAT)
    backup_path = backup_dir / f"{db_path.stem}-{timestamp}{PLAIN_SUFFIX}"

    try:
        # Ensure backup directory exists
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Get source database size for logging
        source_size = db_path.stat().st_size

        logger.info(
            "Starting backup",
            extra={
                "database": db_name,
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
                "Backup file is empty",
                extra={"database": db_name, "backup_path": str(backup_path)},
            )
            backup_path.unlink()  # Remove empty backup
            return False

        logger.info(
            "Backup completed",
            extra={
                "database": db_name,
                "backup_path": str(backup_path),
                "backup_size_bytes": backup_size,
            },
        )
        _compress_logged(backup_path, db_name)
        return True

    except sqlite3.Error as e:
        logger.exception(
            "SQLite error during backup",
            extra={"database": db_name, "path": str(db_path), "error": str(e)},
        )
        # Clean up partial backup if it exists
        if backup_path.exists():
            backup_path.unlink()
        return False
    except OSError as e:
        logger.exception(
            "File error during backup",
            extra={"database": db_name, "path": str(db_path), "error": str(e)},
        )
        return False


def _backup_files(db_path: Path) -> list[tuple[Path, datetime]]:
    """Backups of a database, compressed or plain, with their timestamps.

    Files whose name doesn't parse (partial `.tmp` files, strays) are skipped.
    """
    backup_dir = get_backup_dir(db_path)
    if not backup_dir.exists():
        return []
    found = []
    prefix = f"{db_path.stem}-"
    for file in backup_dir.iterdir():
        suffix = next((x for x in BACKUP_SUFFIXES if file.name.endswith(x)), None)
        if suffix is None or not file.name.startswith(prefix):
            continue
        stamp = file.name.removeprefix(prefix).removesuffix(suffix)
        try:
            when = datetime.strptime(stamp, TIMESTAMP_FORMAT).replace(tzinfo=UTC)
        except ValueError:
            continue
        found.append((file, when))
    return found


def cleanup_old_backups(db_path: Path, db_name: str, retention_days: int) -> int:
    """Remove backups older than retention period.

    Args:
        db_path: Path to the database file
        db_name: Human-readable name for logging
        retention_days: Number of days to keep backups

    Returns:
        Number of backups removed
    """
    removed_count = 0
    now = datetime.now(UTC)

    # {stem}-YYYYMMDD-HHMMSS.db.zst, or .db from before compression
    for backup_file, backup_time in _backup_files(db_path):
        try:
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
        except OSError as e:
            # Skip files that can't be deleted
            logger.warning(
                "Could not process backup file",
                extra={"file": str(backup_file), "error": str(e)},
            )
            continue

    if removed_count > 0:
        logger.info(
            "Cleaned up old backups",
            extra={
                "database": db_name,
                "removed_count": removed_count,
                "retention_days": retention_days,
            },
        )

    return removed_count


def list_backups(db_path: Path) -> list[tuple[Path, int, datetime]]:
    """List existing backups for a database.

    Args:
        db_path: Path to the database file

    Returns:
        List of (path, size_bytes, timestamp) tuples, newest first
    """
    backups = []
    for backup_file, backup_time in _backup_files(db_path):
        try:
            backups.append((backup_file, backup_file.stat().st_size, backup_time))
        except OSError:
            continue

    # Sort by timestamp, newest first
    backups.sort(key=lambda x: x[2], reverse=True)
    return backups


def main() -> int:
    """Run backup on all databases.

    Returns:
        0 if all backups successful, 1 if any failed
    """
    parser = argparse.ArgumentParser(description="Backup Moneypenny databases")
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
    parser.add_argument(
        "--decompress",
        type=Path,
        metavar="PATH",
        help="Decompress a .db.zst backup next to itself and run an integrity check",
    )
    args = parser.parse_args()

    if args.decompress:
        try:
            restored = decompress_backup(args.decompress)
        except (OSError, ValueError) as e:
            print(f"Decompress failed: {e}", file=sys.stderr)
            return 1
        print(f"{restored} (integrity check ok)")
        return 0

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
    logger.error("Database backup completed with errors")
    return 1


if __name__ == "__main__":
    sys.exit(main())
