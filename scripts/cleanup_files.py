#!/usr/bin/env python3
"""File retention cleanup script for AI Chatbot.

Deletes expired attachment blobs from blob storage (videos older than
VIDEO_RETENTION_DAYS, images older than IMAGE_RETENTION_DAYS, other files
older than FILE_RETENTION_DAYS) along with their cached Gemini Files API
URIs. Thumbnails are kept so old conversations still render placeholders.

Usage:
    python scripts/cleanup_files.py

This script is designed to be run via systemd timer (daily) or manually as
needed. Runs are idempotent, so overlapping or repeated invocations are safe.
"""

import sys
from pathlib import Path

# Add parent directory to path so we can import from src
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.file_retention import cleanup_expired_files
from src.utils.logging import get_logger, setup_logging

logger = get_logger(__name__)


def main() -> int:
    setup_logging()
    logger.info("Starting file retention cleanup")
    try:
        counts = cleanup_expired_files()
    except Exception:
        logger.error("File retention cleanup failed", exc_info=True)
        return 1
    logger.info(
        "File retention cleanup finished",
        extra={
            "videos_deleted": counts["videos_deleted"],
            "images_deleted": counts["images_deleted"],
            "files_deleted": counts["files_deleted"],
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
