"""Image processing utilities for thumbnail generation."""

import base64
import binascii
import io
import json
from typing import Any

from PIL import Image, UnidentifiedImageError

from src.api.schemas import ThumbnailStatus
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# MIME type to file extension mapping
MIME_TYPE_TO_EXT: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
}


def generate_thumbnail(
    image_data: str, mime_type: str, max_size: tuple[int, int] | None = None
) -> str | None:
    """Generate a thumbnail from base64-encoded image data.

    Args:
        image_data: Base64-encoded image data
        mime_type: MIME type of the image (e.g., 'image/jpeg')
        max_size: Maximum (width, height) for the thumbnail (defaults to Config.THUMBNAIL_MAX_SIZE)

    Returns:
        Base64-encoded thumbnail data, or None if generation fails
    """
    if max_size is None:
        max_size = Config.THUMBNAIL_MAX_SIZE

    if not mime_type.startswith("image/"):
        return None

    try:
        # Decode base64 image
        image_bytes = base64.b64decode(image_data)
        img: Image.Image = Image.open(io.BytesIO(image_bytes))

        # Handle RGBA images (PNG with transparency)
        if img.mode in ("RGBA", "LA", "P"):
            # Convert to RGB with white background for JPEG output
            if mime_type == "image/jpeg":
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                img = background

        # Generate thumbnail (maintains aspect ratio)
        # Use configurable resampling algorithm (BILINEAR is faster, LANCZOS is higher quality)
        resampling = getattr(
            Image.Resampling, Config.THUMBNAIL_RESAMPLING, Image.Resampling.BILINEAR
        )
        img.thumbnail(max_size, resampling)

        # Save to bytes
        output = io.BytesIO()

        # Use original format or fallback to JPEG
        if mime_type == "image/png":
            img.save(output, format="PNG", optimize=True)
        elif mime_type == "image/gif":
            img.save(output, format="GIF")
        elif mime_type == "image/webp":
            img.save(output, format="WEBP", quality=Config.THUMBNAIL_QUALITY)
        else:
            # Default to JPEG
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(output, format="JPEG", quality=Config.THUMBNAIL_QUALITY, optimize=True)

        # Return base64-encoded thumbnail
        output.seek(0)
        return base64.b64encode(output.read()).decode("utf-8")

    except (binascii.Error, UnidentifiedImageError, OSError) as e:
        logger.error(
            "Error generating thumbnail",
            extra={"mime_type": mime_type, "error": str(e)},
            exc_info=True,
        )
        return None


def process_image_files_sync(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Process a list of files and add thumbnails to images synchronously.

    This is used for tool-generated images where we want synchronous thumbnail
    generation. For user uploads, use background_thumbnails.mark_files_for_thumbnail_generation()
    and background_thumbnails.queue_pending_thumbnails() instead.

    Args:
        files: List of file dictionaries with 'name', 'type', 'data' keys

    Returns:
        Same list with 'thumbnail' and 'thumbnail_status' keys added to image files
    """
    image_count = sum(1 for f in files if f.get("type", "").startswith("image/"))
    if image_count > 0:
        logger.debug(
            "Processing image files for thumbnails (sync)",
            extra={"image_count": image_count, "total_files": len(files)},
        )
    for file in files:
        if file.get("type", "").startswith("image/"):
            thumbnail = generate_thumbnail(file.get("data", ""), file.get("type", ""))
            file["thumbnail"] = thumbnail
            file["thumbnail_status"] = (
                ThumbnailStatus.READY.value if thumbnail else ThumbnailStatus.FAILED.value
            )
            if thumbnail:
                logger.debug(
                    "Thumbnail generated (sync)",
                    extra={"file_name": file.get("name", "unknown"), "file_type": file.get("type")},
                )

    return files


# Keep old name for backwards compatibility (used by extract functions)
def process_image_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Process a list of files and add thumbnails to images.

    DEPRECATED: Use process_image_files_sync() for synchronous processing,
    or background_thumbnails functions for async processing.

    Args:
        files: List of file dictionaries with 'name', 'type', 'data' keys

    Returns:
        Same list with 'thumbnail' and 'thumbnail_status' keys added to image files
    """
    return process_image_files_sync(files)


# ============================================================================
# Tool Result Extraction Helpers
# ============================================================================


def _parse_tool_result_json(msg: dict[str, Any]) -> dict[str, Any] | None:
    """Parse JSON content from a tool result message.

    Args:
        msg: Tool result message dict with 'type' and 'content' keys

    Returns:
        Parsed JSON dict, or None if invalid
    """
    if not isinstance(msg, dict) or msg.get("type") != "tool":
        return None

    content = msg.get("content", "")
    if not content or not isinstance(content, str):
        return None

    try:
        tool_result = json.loads(content)
        if isinstance(tool_result, dict):
            return tool_result
    except (json.JSONDecodeError, TypeError):
        pass

    return None


def _get_full_result_field(tool_result: dict[str, Any], field: str) -> Any | None:
    """Get a field from _full_result if it exists.

    Args:
        tool_result: Parsed tool result dict
        field: Field name to extract from _full_result

    Returns:
        Field value, or None if not present
    """
    full_result = tool_result.get("_full_result")
    if not isinstance(full_result, dict):
        return None
    return full_result.get(field)


def _create_file_entry_with_thumbnail(name: str, mime_type: str, data: str) -> dict[str, Any]:
    """Create a file entry dict with optional thumbnail generation.

    Args:
        name: File name
        mime_type: MIME type
        data: Base64-encoded file data

    Returns:
        File dict with thumbnail added if it's an image
    """
    file_dict: dict[str, Any] = {
        "name": name,
        "type": mime_type,
        "data": data,
    }

    if mime_type.startswith("image/"):
        processed = process_image_files_sync([file_dict])
        if processed:
            file_dict = processed[0]

    return file_dict


def extract_generated_images_from_tool_results(
    tool_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract generated images from tool results.

    Scans tool results for generate_image outputs and extracts the image data
    to be stored as files. The image data is stored in `_full_result.image` to
    avoid sending large base64 data back to the LLM.

    Args:
        tool_results: List of tool result dicts with 'type' and 'content' keys

    Returns:
        List of file dicts with {name, type, data, thumbnail} to store
    """
    files: list[dict[str, Any]] = []

    for msg in tool_results:
        tool_result = _parse_tool_result_json(msg)
        if not tool_result:
            continue

        image_data = _get_full_result_field(tool_result, "image")
        if not isinstance(image_data, dict):
            continue

        image_data_str = image_data.get("data")
        if not isinstance(image_data_str, str) or not image_data_str:
            continue

        # Determine mime type with fallback to PNG
        mime_type = image_data.get("mime_type", "image/png")
        if not isinstance(mime_type, str) or not mime_type.startswith("image/"):
            mime_type = "image/png"

        ext = MIME_TYPE_TO_EXT.get(mime_type, "png")
        file_index = len(files)
        file_entry = _create_file_entry_with_thumbnail(
            name=f"generated_image_{file_index + 1}.{ext}",
            mime_type=mime_type,
            data=image_data_str,
        )
        files.append(file_entry)

    return files


def extract_code_output_files_from_tool_results(
    tool_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract generated files from execute_code tool results.

    Scans tool results for execute_code outputs and extracts the file data
    to be stored as message attachments. Files are stored in `_full_result.files`
    to avoid sending large base64 data back to the LLM.

    Args:
        tool_results: List of tool result dicts with 'type' and 'content' keys

    Returns:
        List of file dicts with {name, type, data, thumbnail?} to store
    """
    files: list[dict[str, Any]] = []

    for msg in tool_results:
        tool_result = _parse_tool_result_json(msg)
        if not tool_result:
            continue

        result_files = _get_full_result_field(tool_result, "files")
        if not isinstance(result_files, list):
            continue

        for file_entry in result_files:
            if not isinstance(file_entry, dict):
                continue

            name = file_entry.get("name")
            data = file_entry.get("data")
            if not isinstance(name, str) or not isinstance(data, str):
                continue
            if not name or not data:
                continue

            mime_type = file_entry.get("mime_type", "application/octet-stream")
            file_dict = _create_file_entry_with_thumbnail(name, mime_type, data)
            files.append(file_dict)

    return files
