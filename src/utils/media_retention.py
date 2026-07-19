"""Media retention policy helpers.

Media attachments are not permanent storage: videos are retained for
VIDEO_RETENTION_DAYS, images for IMAGE_RETENTION_DAYS. Expiry is derived
from message age, so callers (history labeling, retrieve_file, file routes)
stay truthful even before the physical sweep has run.

Message timestamps are naive local datetimes; compare with datetime.now().
"""

import threading
from datetime import datetime, timedelta

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

CLEANUP_INTERVAL_SECONDS = 3600  # hourly tick; sweep runs at most daily
CLEANUP_MIN_PERIOD_HOURS = 24
_cleanup_thread: threading.Thread | None = None
_stop_event = threading.Event()


def retention_days_for_mime(mime_type: str) -> int | None:
    """Retention window in days for a MIME type, or None if never expires."""
    if mime_type.startswith("video/"):
        return Config.VIDEO_RETENTION_DAYS
    if mime_type.startswith("image/"):
        return Config.IMAGE_RETENTION_DAYS
    return None


def is_media_expired(mime_type: str, created_at: datetime, now: datetime | None = None) -> bool:
    """Whether a media file has passed its retention window."""
    days = retention_days_for_mime(mime_type)
    if days is None:
        return False
    now = now or datetime.now()
    return created_at < now - timedelta(days=days)


def retention_note(mime_type: str) -> str:
    """Human/LLM-readable description of the retention policy for a type."""
    days = retention_days_for_mime(mime_type)
    if days is None:
        return "This file type is not subject to retention cleanup"
    kind = "Videos" if mime_type.startswith("video/") else "Images"
    return f"{kind} are retained for {days} days"


def cleanup_expired_media() -> dict[str, int]:
    """Delete expired media blobs and their Gemini URI cache entries.

    Thumbnails are intentionally kept so old conversations still render a
    placeholder. Idempotent: deleting an already-deleted blob is a no-op.
    """
    # Imports at call time so tests can patch the module-level singletons
    from src.agent.gemini_files import delete_cached_file_uri
    from src.db import models
    from src.db.blob_store import get_blob_store
    from src.db.models import make_blob_key

    counts = {"videos_deleted": 0, "images_deleted": 0}
    blob_store = get_blob_store()
    now = datetime.now()
    # Videos have the shortest window, so its cutoff bounds the scan
    cutoff = now - timedelta(days=Config.VIDEO_RETENTION_DAYS)

    for msg in models.db.get_messages_with_files_before(cutoff):
        for idx, file in enumerate(msg.files or []):
            mime_type = file.get("type", "")
            if not is_media_expired(mime_type, msg.created_at, now=now):
                continue
            if blob_store.delete(make_blob_key(msg.id, idx)):
                key = "videos_deleted" if mime_type.startswith("video/") else "images_deleted"
                counts[key] += 1
            if mime_type.startswith("video/"):
                delete_cached_file_uri(msg.id, idx)

    if counts["videos_deleted"] or counts["images_deleted"]:
        logger.info("Media retention sweep completed", extra=counts)
    return counts


def run_media_cleanup_if_due() -> bool:
    """Run the sweep if the last run was over CLEANUP_MIN_PERIOD_HOURS ago.

    The kv timestamp acts as a soft cross-worker lock: with 4 gunicorn
    workers ticking hourly, at most a couple race on the same day, and the
    sweep is idempotent so a duplicate run is harmless.
    """
    from src.db import models
    from src.utils.datetime_utils import utcnow_naive

    last_run = models.db.kv_get("_system", "media_cleanup", "last_run")
    if last_run:
        try:
            if datetime.fromisoformat(last_run) > utcnow_naive() - timedelta(
                hours=CLEANUP_MIN_PERIOD_HOURS
            ):
                return False
        except ValueError:
            pass
    models.db.kv_set("_system", "media_cleanup", "last_run", utcnow_naive().isoformat())
    cleanup_expired_media()
    return True


def _cleanup_loop() -> None:
    while not _stop_event.is_set():
        try:
            run_media_cleanup_if_due()
        except Exception:
            logger.error("Media cleanup sweep failed", exc_info=True)
        _stop_event.wait(CLEANUP_INTERVAL_SECONDS)


def start_media_cleanup_thread() -> None:
    """Start the daily media retention sweep (idempotent per process)."""
    global _cleanup_thread
    if _cleanup_thread is not None and _cleanup_thread.is_alive():
        return
    _cleanup_thread = threading.Thread(target=_cleanup_loop, daemon=True, name="media-cleanup")
    _cleanup_thread.start()
    logger.info("Media cleanup thread started")
