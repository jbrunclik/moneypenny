"""File retention policy helpers.

Attachments are not permanent storage: videos are retained for
VIDEO_RETENTION_DAYS, images for IMAGE_RETENTION_DAYS, and all other file
types (PDFs, text, JSON, CSV) for FILE_RETENTION_DAYS. Expiry is derived
from message age, so callers (history labeling, retrieve_file, file routes)
stay truthful even before the physical sweep has run.

The sweep itself runs via systemd timer in production
(ai-chatbot-file-cleanup.timer -> scripts/cleanup_files.py) and via the dev
scheduler loop in development.

Message timestamps are naive local datetimes; compare with datetime.now().
"""

from datetime import datetime, timedelta

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

CLEANUP_MIN_PERIOD_HOURS = 24


def retention_days_for_mime(mime_type: str) -> int:
    """Retention window in days for a MIME type."""
    if mime_type.startswith("video/"):
        return Config.VIDEO_RETENTION_DAYS
    if mime_type.startswith("image/"):
        return Config.IMAGE_RETENTION_DAYS
    return Config.FILE_RETENTION_DAYS


def is_file_expired(mime_type: str, created_at: datetime, now: datetime | None = None) -> bool:
    """Whether an attachment has passed its retention window."""
    days = retention_days_for_mime(mime_type)
    now = now or datetime.now()
    return created_at < now - timedelta(days=days)


def retention_note(mime_type: str) -> str:
    """Human/LLM-readable description of the retention policy for a type."""
    days = retention_days_for_mime(mime_type)
    if mime_type.startswith("video/"):
        kind = "Videos"
    elif mime_type.startswith("image/"):
        kind = "Images"
    else:
        kind = "Files"
    return f"{kind} are retained for {days} days"


def cleanup_expired_files() -> dict[str, int]:
    """Delete expired attachment blobs and their Gemini URI cache entries.

    Thumbnails are intentionally kept so old conversations still render a
    placeholder. Idempotent: deleting an already-deleted blob is a no-op.
    """
    # Imports at call time so tests can patch the module-level singletons
    from src.agent.gemini_files import delete_cached_file_uri
    from src.db import models
    from src.db.blob_store import get_blob_store
    from src.db.models import make_blob_key

    counts = {"videos_deleted": 0, "images_deleted": 0, "files_deleted": 0}
    blob_store = get_blob_store()
    now = datetime.now()
    # The shortest retention window bounds the scan
    min_days = min(
        Config.VIDEO_RETENTION_DAYS,
        Config.IMAGE_RETENTION_DAYS,
        Config.FILE_RETENTION_DAYS,
    )
    cutoff = now - timedelta(days=min_days)

    for msg in models.db.get_messages_with_files_before(cutoff):
        for idx, file in enumerate(msg.files or []):
            mime_type = file.get("type", "")
            if not is_file_expired(mime_type, msg.created_at, now=now):
                continue
            if blob_store.delete(make_blob_key(msg.id, idx)):
                if mime_type.startswith("video/"):
                    counts["videos_deleted"] += 1
                elif mime_type.startswith("image/"):
                    counts["images_deleted"] += 1
                else:
                    counts["files_deleted"] += 1
            if mime_type.startswith("video/"):
                delete_cached_file_uri(msg.id, idx)

    if any(counts.values()):
        logger.info("File retention sweep completed", extra=counts)
    return counts


def run_file_cleanup_if_due() -> bool:
    """Run the sweep if the last run was over CLEANUP_MIN_PERIOD_HOURS ago.

    Used by the dev scheduler loop (production uses the systemd timer, which
    is its own schedule — scripts/cleanup_files.py calls cleanup_expired_files
    directly). The kv timestamp keeps the minutely dev loop from sweeping
    more than daily; the sweep is idempotent, so races are harmless.
    """
    from src.db import models
    from src.utils.datetime_utils import utcnow_naive

    last_run = models.db.kv_get("_system", "file_cleanup", "last_run")
    if last_run:
        try:
            if datetime.fromisoformat(last_run) > utcnow_naive() - timedelta(
                hours=CLEANUP_MIN_PERIOD_HOURS
            ):
                return False
        except ValueError:
            pass
    models.db.kv_set("_system", "file_cleanup", "last_run", utcnow_naive().isoformat())
    cleanup_expired_files()
    return True
