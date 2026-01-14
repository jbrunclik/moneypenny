"""File serving routes: thumbnails and full files.

This module handles serving image files (thumbnails and full-size) from messages.
"""

import base64
import binascii
from datetime import datetime
from typing import Any

from apiflask import APIBlueprint
from flask import Response

from src.api.errors import (
    raise_auth_forbidden_error,
    raise_not_found_error,
    raise_validation_error,
)
from src.api.rate_limiting import rate_limit_files
from src.api.schemas import ThumbnailStatus
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.blob_store import get_blob_store
from src.db.models import User, db, make_blob_key, make_thumbnail_key
from src.utils.background_thumbnails import generate_and_save_thumbnail
from src.utils.logging import get_logger

logger = get_logger(__name__)

api = APIBlueprint("files", __name__, url_prefix="/api", tag="Files")


# ============================================================================
# Image Routes
# ============================================================================


@api.route("/messages/<message_id>/files/<int:file_index>/thumbnail", methods=["GET"])
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

    blob_store = get_blob_store()

    # Check thumbnail status (default to "ready" for legacy messages without status)
    thumbnail_status = file.get("thumbnail_status", ThumbnailStatus.READY.value)

    # Handle pending thumbnail with stale recovery
    if thumbnail_status == ThumbnailStatus.PENDING.value:
        # Check if message is old enough that generation should have completed
        # If pending for more than threshold, assume the worker died and regenerate synchronously
        message_age = (datetime.now() - message.created_at).total_seconds()
        if message_age > Config.THUMBNAIL_STALE_THRESHOLD_SECONDS:
            logger.warning(
                "Stale pending thumbnail detected, regenerating synchronously",
                extra={
                    "user_id": user.id,
                    "message_id": message_id,
                    "file_index": file_index,
                    "message_age_seconds": message_age,
                    "threshold_seconds": Config.THUMBNAIL_STALE_THRESHOLD_SECONDS,
                },
            )
            # Get full image from blob store for regeneration
            blob_key = make_blob_key(message_id, file_index)
            blob_result = blob_store.get(blob_key)
            if blob_result:
                file_bytes, _ = blob_result
                file_data_b64 = base64.b64encode(file_bytes).decode("utf-8")
                # Regenerate synchronously (one-time recovery) using shared helper
                thumbnail = generate_and_save_thumbnail(
                    message_id, file_index, file_data_b64, file_type
                )
                if thumbnail:
                    try:
                        binary_data = base64.b64decode(thumbnail)
                        return Response(
                            binary_data,
                            mimetype="image/jpeg",
                            headers={"Cache-Control": "private, max-age=31536000"},
                        )
                    except binascii.Error:
                        pass  # Fall through to full image
            # Fall through to full image fallback below
        else:
            # Not stale yet - return 202 to signal frontend to poll
            logger.debug(
                "Thumbnail pending, returning 202",
                extra={
                    "user_id": user.id,
                    "message_id": message_id,
                    "file_index": file_index,
                    "message_age_seconds": message_age,
                },
            )
            return {"status": "pending"}, 202

    # Try to get thumbnail from blob store
    has_thumbnail = file.get("has_thumbnail", False)
    # Also check legacy "thumbnail" field for migration compatibility
    has_legacy_thumbnail = "thumbnail" in file and file["thumbnail"]

    if has_thumbnail or has_legacy_thumbnail:
        # Try blob store first (new format)
        thumb_key = make_thumbnail_key(message_id, file_index)
        thumb_result = blob_store.get(thumb_key)
        if thumb_result:
            binary_data, mime_type = thumb_result
            logger.debug(
                "Returning thumbnail from blob store",
                extra={
                    "user_id": user.id,
                    "message_id": message_id,
                    "conversation_id": message.conversation_id,
                    "file_index": file_index,
                    "size": len(binary_data),
                },
            )
            return Response(
                binary_data,
                mimetype=mime_type,
                headers={"Cache-Control": "private, max-age=31536000"},
            )

        # Try legacy base64 thumbnail (for unmigrated messages)
        if has_legacy_thumbnail:
            try:
                binary_data = base64.b64decode(file["thumbnail"])
                logger.debug(
                    "Returning legacy thumbnail",
                    extra={
                        "user_id": user.id,
                        "message_id": message_id,
                        "conversation_id": message.conversation_id,
                        "file_index": file_index,
                        "size": len(binary_data),
                    },
                )
                return Response(
                    binary_data,
                    mimetype="image/jpeg",
                    headers={"Cache-Control": "private, max-age=31536000"},
                )
            except binascii.Error as e:
                logger.warning(
                    "Failed to decode legacy thumbnail",
                    extra={"message_id": message_id, "error": str(e)},
                )

    # Fall back to full image from blob store
    blob_key = make_blob_key(message_id, file_index)
    blob_result = blob_store.get(blob_key)
    if blob_result:
        binary_data, mime_type = blob_result
        logger.debug(
            "Returning full image as thumbnail fallback",
            extra={
                "user_id": user.id,
                "message_id": message_id,
                "conversation_id": message.conversation_id,
                "file_index": file_index,
                "size": len(binary_data),
            },
        )
        return Response(
            binary_data,
            mimetype=mime_type,
            headers={"Cache-Control": "private, max-age=31536000"},
        )

    # Try legacy base64 data (for unmigrated messages)
    file_data = file.get("data", "")
    if file_data:
        try:
            binary_data = base64.b64decode(file_data)
            logger.debug(
                "Returning legacy full image as thumbnail fallback",
                extra={
                    "user_id": user.id,
                    "message_id": message_id,
                    "conversation_id": message.conversation_id,
                    "file_index": file_index,
                    "size": len(binary_data),
                },
            )
            return Response(
                binary_data,
                mimetype=file_type,
                headers={"Cache-Control": "private, max-age=31536000"},
            )
        except binascii.Error as e:
            logger.error("Failed to decode legacy image data", extra={"error": str(e)})

    logger.warning(
        "No image data found for thumbnail",
        extra={
            "user_id": user.id,
            "message_id": message_id,
            "conversation_id": message.conversation_id,
            "file_index": file_index,
        },
    )
    raise_not_found_error("Image data")


@api.route("/messages/<message_id>/files/<int:file_index>", methods=["GET"])
@api.doc(
    summary="Get full file from a message",
    description="Returns the file as binary data with appropriate content-type header.",
    responses=[403, 404, 429],
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

    # Try blob store first (new format)
    blob_store = get_blob_store()
    blob_key = make_blob_key(message_id, file_index)
    blob_result = blob_store.get(blob_key)
    if blob_result:
        binary_data, mime_type = blob_result
        logger.debug(
            "Returning file from blob store",
            extra={
                "user_id": user.id,
                "message_id": message_id,
                "conversation_id": message.conversation_id,
                "file_index": file_index,
                "file_type": mime_type,
                "size": len(binary_data),
            },
        )
        return Response(
            binary_data,
            mimetype=mime_type,
            headers={"Cache-Control": "private, max-age=31536000"},
        )

    # Fall back to legacy base64 data (for unmigrated messages)
    file_data = file.get("data", "")
    if file_data:
        try:
            binary_data = base64.b64decode(file_data)
            logger.debug(
                "Returning legacy file",
                extra={
                    "user_id": user.id,
                    "message_id": message_id,
                    "conversation_id": message.conversation_id,
                    "file_index": file_index,
                    "file_type": file_type,
                    "size": len(binary_data),
                },
            )
            return Response(
                binary_data,
                mimetype=file_type,
                headers={"Cache-Control": "private, max-age=31536000"},
            )
        except binascii.Error as e:
            logger.error("Failed to decode legacy file data", extra={"error": str(e)})

    logger.warning(
        "No file data found",
        extra={
            "user_id": user.id,
            "message_id": message_id,
            "conversation_id": message.conversation_id,
            "file_index": file_index,
        },
    )
    raise_not_found_error("File data")
