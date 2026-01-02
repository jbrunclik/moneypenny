"""Background thumbnail generation using ThreadPoolExecutor.

This module provides non-blocking thumbnail generation for uploaded images.
Thumbnails are generated in background threads and the database is updated
when complete.
"""

import base64
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from src.api.schemas import ThumbnailStatus
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Module-level executor (created on first use, lazy initialization)
_executor: ThreadPoolExecutor | None = None


def get_executor() -> ThreadPoolExecutor:
    """Get or create the thumbnail generation executor.

    Uses lazy initialization to avoid creating threads until needed.
    """
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=Config.THUMBNAIL_WORKER_THREADS,
            thread_name_prefix="thumbnail-",
        )
        logger.debug(
            "Created thumbnail executor",
            extra={"max_workers": Config.THUMBNAIL_WORKER_THREADS},
        )
    return _executor


def should_skip_thumbnail(file_data: str, file_type: str) -> bool:
    """Determine if thumbnail generation should be skipped.

    Returns True if:
    - File is not an image
    - File is small enough that original can be used as thumbnail

    Args:
        file_data: Base64-encoded file data
        file_type: MIME type of the file

    Returns:
        True if thumbnail generation should be skipped
    """
    if not file_type.startswith("image/"):
        return True

    try:
        data_size = len(base64.b64decode(file_data))
        return data_size < Config.THUMBNAIL_SKIP_THRESHOLD_BYTES
    except Exception:
        # If we can't decode, don't skip - let thumbnail generation handle the error
        return False


def queue_thumbnail_generation(
    message_id: str, file_index: int, file_data: str, file_type: str
) -> None:
    """Queue thumbnail generation for background processing.

    Args:
        message_id: ID of the message containing the file
        file_index: Index of the file in the message's files array
        file_data: Base64-encoded image data
        file_type: MIME type of the image
    """
    logger.debug(
        "Queueing thumbnail generation",
        extra={"message_id": message_id, "file_index": file_index, "file_type": file_type},
    )
    get_executor().submit(_generate_thumbnail_task, message_id, file_index, file_data, file_type)


def generate_and_save_thumbnail(
    message_id: str, file_index: int, file_data: str, file_type: str
) -> str | None:
    """Generate a thumbnail and save it to the database.

    This is the shared helper used by both background generation and
    synchronous stale recovery.

    Args:
        message_id: ID of the message containing the file
        file_index: Index of the file in the message's files array
        file_data: Base64-encoded image data
        file_type: MIME type of the image

    Returns:
        The generated thumbnail (base64 string) or None if generation failed
    """
    # Import here to avoid circular imports
    from src.db.models import db
    from src.utils.images import generate_thumbnail

    logger.debug(
        "Generating thumbnail",
        extra={"message_id": message_id, "file_index": file_index},
    )

    thumbnail = generate_thumbnail(file_data, file_type)
    status = ThumbnailStatus.READY if thumbnail else ThumbnailStatus.FAILED

    # Update the database with the generated thumbnail
    success = db.update_message_file_thumbnail(
        message_id,
        file_index,
        thumbnail,
        status=status,
    )

    if success:
        logger.debug(
            "Thumbnail saved to database",
            extra={
                "message_id": message_id,
                "file_index": file_index,
                "status": status.value,
            },
        )
    else:
        logger.warning(
            "Failed to update thumbnail in database (message may have been deleted)",
            extra={"message_id": message_id, "file_index": file_index},
        )

    return thumbnail


def _generate_thumbnail_task(
    message_id: str, file_index: int, file_data: str, file_type: str
) -> None:
    """Background task to generate and save a thumbnail.

    This runs in a ThreadPoolExecutor worker thread. Wraps generate_and_save_thumbnail
    with exception handling for background execution.

    Args:
        message_id: ID of the message containing the file
        file_index: Index of the file in the message's files array
        file_data: Base64-encoded image data
        file_type: MIME type of the image
    """
    try:
        generate_and_save_thumbnail(message_id, file_index, file_data, file_type)
    except Exception as e:
        logger.error(
            "Thumbnail generation failed",
            extra={"message_id": message_id, "file_index": file_index, "error": str(e)},
            exc_info=True,
        )
        # Try to mark as failed in database
        try:
            from src.db.models import db

            db.update_message_file_thumbnail(
                message_id, file_index, None, status=ThumbnailStatus.FAILED
            )
        except Exception:
            # Message might have been deleted, ignore
            pass


def mark_files_for_thumbnail_generation(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark files with appropriate thumbnail status before saving.

    This should be called BEFORE saving the message to the database.
    It marks each image file with either:
    - thumbnail_status: ThumbnailStatus.READY with thumbnail data (for small images)
    - thumbnail_status: ThumbnailStatus.PENDING (for large images that need background generation)

    Args:
        files: List of file dictionaries with 'name', 'type', 'data' keys

    Returns:
        The same list with thumbnail_status (and possibly thumbnail) added
    """
    for file in files:
        file_type = file.get("type", "")
        file_data = file.get("data", "")

        if not file_type.startswith("image/"):
            # Non-image files don't need thumbnails
            continue

        if should_skip_thumbnail(file_data, file_type):
            # Small image - use original data as thumbnail
            file["thumbnail"] = file_data
            file["thumbnail_status"] = ThumbnailStatus.READY.value
            logger.debug(
                "Small image - using original as thumbnail",
                extra={"file_name": file.get("name"), "file_type": file_type},
            )
        else:
            # Large image - mark as pending for background generation
            file["thumbnail_status"] = ThumbnailStatus.PENDING.value
            logger.debug(
                "Large image - marking for background generation",
                extra={"file_name": file.get("name"), "file_type": file_type},
            )

    return files


def queue_pending_thumbnails(message_id: str, files: list[dict[str, Any]]) -> None:
    """Queue background thumbnail generation for all pending files.

    This should be called AFTER saving the message to the database,
    using the message ID.

    Args:
        message_id: ID of the saved message
        files: List of file dictionaries (same as passed to add_message)
    """
    for idx, file in enumerate(files):
        if file.get("thumbnail_status") == ThumbnailStatus.PENDING.value:
            queue_thumbnail_generation(message_id, idx, file.get("data", ""), file.get("type", ""))
