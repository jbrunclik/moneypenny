"""File serving routes: thumbnails and full files.

This module handles serving image files (thumbnails and full-size) from messages.
"""

import base64
import binascii
from typing import Any

from apiflask import APIBlueprint
from flask import Response

from src.api.errors import (
    raise_auth_forbidden_error,
    raise_gone_error,
    raise_not_found_error,
    raise_validation_error,
)
from src.api.rate_limiting import rate_limit_files
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.blob_store import get_blob_store
from src.db.models import Message, User, db, make_blob_key, make_thumbnail_key
from src.enums import ThumbnailStatus
from src.services.background_thumbnails import generate_and_save_thumbnail
from src.services.file_retention import is_file_expired, retention_note
from src.utils.clock import utc_now
from src.utils.images import transcode_image_for_browser
from src.utils.logging import get_logger

logger = get_logger(__name__)

api = APIBlueprint("files", __name__, url_prefix="/api", tag="Files")


# ============================================================================
# Image Routes
# ============================================================================


@api.route("/messages/<message_id>/files/<int:file_index>/thumbnail", methods=["GET"])  # noqa: RET503 - ends in raise_not_found_error() (NoReturn, in another module)
@api.doc(
    summary="Get thumbnail for an image file",
    description="Returns thumbnail binary data (200) or pending status (202).",
    responses=[202, 403, 404, 429],
)
@rate_limit_files
@require_auth
def get_message_thumbnail(
    user: User, message_id: str, file_index: int
) -> Response | tuple[dict[str, Any], int]:
    """Get a thumbnail for an image file from a message.

    Thumbnails are stored in the blob store (files.db).

    Returns:
        - 200 with thumbnail binary data when ready
        - 202 with {"status": "pending"} when thumbnail is still being generated
        - Falls back to full image if thumbnail generation failed
    """
    logger.debug(
        "Getting thumbnail",
        extra={"user_id": user.id, "message_id": message_id, "file_index": file_index},
    )

    message, file = _thumbnail_image_file(user, message_id, file_index)
    file_type = file.get("type", "application/octet-stream")
    log_extra = {
        "user_id": user.id,
        "message_id": message_id,
        "conversation_id": message.conversation_id,
        "file_index": file_index,
    }

    # Check thumbnail status (default to "ready" for legacy messages without status)
    thumbnail_status = file.get("thumbnail_status", ThumbnailStatus.READY.value)

    # Handle pending thumbnail with stale recovery
    if thumbnail_status == ThumbnailStatus.PENDING.value:
        pending = _pending_thumbnail(user, message, file_index, file_type)
        if pending is not None:
            return pending
        # Fall through to full image fallback below

    response = _stored_thumbnail(message_id, file_index, file, log_extra)
    if response is None:
        response = _full_image_fallback(message_id, file_index, file, file_type, log_extra)
    if response is not None:
        return response

    logger.warning("No image data found for thumbnail", extra=log_extra)
    raise_not_found_error("Image data")


def _cached_image(binary_data: bytes, mimetype: str) -> Response:
    """An image response the browser may cache for a year (file contents never change)."""
    return Response(
        binary_data,
        mimetype=mimetype,
        headers={"Cache-Control": "private, max-age=31536000"},
    )


def _thumbnail_image_file(
    user: User, message_id: str, file_index: int
) -> tuple[Message, dict[str, Any]]:
    """The message and image file a thumbnail request names (raises 403/404/400)."""
    # Get the message
    message = db.get_message_by_id(message_id)
    if not message:
        logger.warning("Message not found for thumbnail", extra={"message_id": message_id})
        raise_not_found_error("Message")

    # Verify user owns the conversation
    conv = db.get_conversation(message.conversation_id, user.id)
    if not conv:
        logger.warning(
            "Unauthorized thumbnail access", extra={"user_id": user.id, "message_id": message_id}
        )
        raise_auth_forbidden_error("Not authorized to access this resource")

    # Get the file metadata
    if not message.files or file_index >= len(message.files):
        logger.warning(
            "File not found for thumbnail",
            extra={"message_id": message_id, "file_index": file_index},
        )
        raise_not_found_error("File")

    file = message.files[file_index]
    file_type = file.get("type", "application/octet-stream")

    # Check if it's an image
    if not file_type.startswith("image/"):
        logger.warning(
            "Non-image file requested as thumbnail",
            extra={
                "user_id": user.id,
                "message_id": message_id,
                "conversation_id": message.conversation_id,
                "file_type": file_type,
            },
        )
        raise_validation_error("File is not an image", field="file_type")
    return message, file


def _pending_thumbnail(
    user: User, message: Message, file_index: int, file_type: str
) -> Response | tuple[dict[str, Any], int] | None:
    """202 while a thumbnail is being generated; a stale one is regenerated in place.

    None when a stale regeneration failed, so the caller falls back to the image.
    """
    # Check if message is old enough that generation should have completed
    # If pending for more than threshold, assume the worker died and regenerate synchronously
    message_age = (utc_now() - message.created_at).total_seconds()
    if message_age <= Config.THUMBNAIL_STALE_THRESHOLD_SECONDS:
        # Not stale yet - return 202 to signal frontend to poll
        logger.debug(
            "Thumbnail pending, returning 202",
            extra={
                "user_id": user.id,
                "message_id": message.id,
                "file_index": file_index,
                "message_age_seconds": message_age,
            },
        )
        return {"status": "pending"}, 202

    logger.warning(
        "Stale pending thumbnail detected, regenerating synchronously",
        extra={
            "user_id": user.id,
            "message_id": message.id,
            "file_index": file_index,
            "message_age_seconds": message_age,
            "threshold_seconds": Config.THUMBNAIL_STALE_THRESHOLD_SECONDS,
        },
    )
    # Get full image from blob store for regeneration
    blob_result = get_blob_store().get(make_blob_key(message.id, file_index))
    if not blob_result:
        return None
    file_bytes, _ = blob_result
    file_data_b64 = base64.b64encode(file_bytes).decode("utf-8")
    # Regenerate synchronously (one-time recovery) using shared helper
    thumbnail = generate_and_save_thumbnail(message.id, file_index, file_data_b64, file_type)
    if not thumbnail:
        return None
    try:
        return _cached_image(base64.b64decode(thumbnail), "image/jpeg")
    except binascii.Error:
        return None  # Fall through to full image


def _stored_thumbnail(
    message_id: str, file_index: int, file: dict[str, Any], log_extra: dict[str, Any]
) -> Response | None:
    """The saved thumbnail (blob store, else the legacy base64 field), if there is one."""
    has_thumbnail = file.get("has_thumbnail", False)
    # Also check legacy "thumbnail" field for migration compatibility
    has_legacy_thumbnail = "thumbnail" in file and file["thumbnail"]
    if not has_thumbnail and not has_legacy_thumbnail:
        return None

    # Try blob store first (new format)
    thumb_result = get_blob_store().get(make_thumbnail_key(message_id, file_index))
    if thumb_result:
        binary_data, mime_type = thumb_result
        logger.debug(
            "Returning thumbnail from blob store",
            extra={**log_extra, "size": len(binary_data)},
        )
        return _cached_image(binary_data, mime_type)

    # Try legacy base64 thumbnail (for unmigrated messages)
    if not has_legacy_thumbnail:
        return None
    try:
        binary_data = base64.b64decode(file["thumbnail"])
    except binascii.Error as e:
        logger.warning(
            "Failed to decode legacy thumbnail",
            extra={"message_id": message_id, "error": str(e)},
        )
        return None
    logger.debug("Returning legacy thumbnail", extra={**log_extra, "size": len(binary_data)})
    return _cached_image(binary_data, "image/jpeg")


def _full_image_fallback(
    message_id: str,
    file_index: int,
    file: dict[str, Any],
    file_type: str,
    log_extra: dict[str, Any],
) -> Response | None:
    """The full image in place of a missing thumbnail (blob store, else legacy base64)."""
    blob_result = get_blob_store().get(make_blob_key(message_id, file_index))
    if blob_result:
        binary_data, mime_type = blob_result
        logger.debug(
            "Returning full image as thumbnail fallback",
            extra={**log_extra, "size": len(binary_data)},
        )
        return _cached_image(binary_data, mime_type)

    # Try legacy base64 data (for unmigrated messages)
    file_data = file.get("data", "")
    if not file_data:
        return None
    try:
        binary_data = base64.b64decode(file_data)
    except binascii.Error as e:
        logger.error("Failed to decode legacy image data", extra={"error": str(e)})  # noqa: TRY400 - corrupt stored data
        return None
    logger.debug(
        "Returning legacy full image as thumbnail fallback",
        extra={**log_extra, "size": len(binary_data)},
    )
    return _cached_image(binary_data, file_type)


@api.route("/messages/<message_id>/files/<int:file_index>", methods=["GET"])  # noqa: RET503 - ends in raise_not_found_error() (NoReturn, in another module)
@api.doc(
    summary="Get full file from a message",
    description="Returns the file as binary data with appropriate content-type header.",
    responses=[403, 404, 410, 429],
)
@rate_limit_files
@require_auth
def get_message_file(
    user: User, message_id: str, file_index: int
) -> Response | tuple[dict[str, str], int]:
    """Get a full-size file from a message.

    Files are stored in the blob store (files.db).
    Falls back to legacy base64 data for unmigrated messages.

    Returns the file as binary data with appropriate content-type header.
    """
    logger.debug(
        "Getting file",
        extra={"user_id": user.id, "message_id": message_id, "file_index": file_index},
    )

    message, file = _requested_file(user, message_id, file_index)
    file_type = file.get("type", "application/octet-stream")
    log_extra = {
        "user_id": user.id,
        "message_id": message_id,
        "conversation_id": message.conversation_id,
        "file_index": file_index,
    }

    response = _blob_file(message_id, file_index, log_extra)
    if response is None:
        response = _legacy_file(file, file_type, log_extra)
    if response is not None:
        return response

    logger.warning("No file data found", extra=log_extra)
    raise_not_found_error("File data")


def _requested_file(user: User, message_id: str, file_index: int) -> tuple[Message, dict[str, Any]]:
    """The message and file a file request names (raises 403/404/410)."""
    # Get the message
    message = db.get_message_by_id(message_id)
    if not message:
        logger.warning(
            "Message not found for file", extra={"user_id": user.id, "message_id": message_id}
        )
        raise_not_found_error("Message")

    # Verify user owns the conversation
    conv = db.get_conversation(message.conversation_id, user.id)
    if not conv:
        logger.warning(
            "Unauthorized file access",
            extra={
                "user_id": user.id,
                "message_id": message_id,
                "conversation_id": message.conversation_id,
            },
        )
        raise_auth_forbidden_error("Not authorized to access this resource")

    # Get the file metadata
    if not message.files or file_index >= len(message.files):
        logger.warning(
            "File not found",
            extra={
                "user_id": user.id,
                "message_id": message_id,
                "conversation_id": message.conversation_id,
                "file_index": file_index,
            },
        )
        raise_not_found_error("File")

    file = message.files[file_index]
    file_type = file.get("type", "application/octet-stream")

    # Age-based retention gate: expired media is (or is about to be) deleted
    if is_file_expired(file_type, message.created_at):
        logger.info(
            "Expired media requested",
            extra={
                "user_id": user.id,
                "message_id": message_id,
                "file_index": file_index,
                "file_type": file_type,
            },
        )
        raise_gone_error(f"This file has been cleaned up. {retention_note(file_type)}.")
    return message, file


def _blob_file(message_id: str, file_index: int, log_extra: dict[str, Any]) -> Response | None:
    """The file from the blob store (new format), or None when it isn't there."""
    blob_result = get_blob_store().get(make_blob_key(message_id, file_index))
    if not blob_result:
        return None
    binary_data, mime_type = blob_result
    # HEIC/HEIF originals are transcoded to JPEG - browsers other than
    # Safari cannot render them in <img> (lightbox full-size view)
    binary_data, mime_type = transcode_image_for_browser(binary_data, mime_type)
    logger.debug(
        "Returning file from blob store",
        extra={**log_extra, "file_type": mime_type, "size": len(binary_data)},
    )
    return _cached_image(binary_data, mime_type)


def _legacy_file(
    file: dict[str, Any], file_type: str, log_extra: dict[str, Any]
) -> Response | None:
    """The file from legacy base64 data (unmigrated messages), or None."""
    file_data = file.get("data", "")
    if not file_data:
        return None
    try:
        binary_data = base64.b64decode(file_data)
    except binascii.Error as e:
        logger.error("Failed to decode legacy file data", extra={"error": str(e)})  # noqa: TRY400 - corrupt stored data
        return None
    binary_data, file_type = transcode_image_for_browser(binary_data, file_type)
    logger.debug(
        "Returning legacy file",
        extra={**log_extra, "file_type": file_type, "size": len(binary_data)},
    )
    return _cached_image(binary_data, file_type)
