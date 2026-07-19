"""Media retention policy helpers.

Media attachments are not permanent storage: videos are retained for
VIDEO_RETENTION_DAYS, images for IMAGE_RETENTION_DAYS. Expiry is derived
from message age, so callers (history labeling, retrieve_file, file routes)
stay truthful even before the physical sweep has run.

Message timestamps are naive local datetimes; compare with datetime.now().
"""

from datetime import datetime, timedelta

from src.config import Config


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
