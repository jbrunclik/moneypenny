"""File retrieval tool for accessing files from conversation history."""

import base64
import json
from typing import Any

from langchain_core.tools import tool

from src.agent.tools.context import get_conversation_context
from src.config import Config
from src.utils.images import downscale_image_for_reference
from src.utils.logging import get_logger

logger = get_logger(__name__)


@tool
def retrieve_file(
    message_id: str,
    file_index: int = 0,
) -> str | list[dict[str, Any]]:
    """Retrieve a file from conversation history for analysis.

    Use this tool to:
    - Retrieve a specific file by message_id and file_index for analysis
    - Get images from earlier messages to use with generate_image as references
    - View a video from an earlier message again (videos are only attached on
      the turn they were uploaded)

    Retention: uploaded attachments are temporary — videos are kept 7 days,
    images and other files 30 days. Expired files return an error explaining
    the cleanup.

    The message_id and file_index can be found in the conversation history metadata.
    Each user message with files includes a "files" array with "id" in format "message_id:file_index".

    Args:
        message_id: The message ID containing the file (from history metadata).
        file_index: Index of the file in the message (0-based, default 0).

    Returns:
        Multimodal content with the file data for analysis (images, PDFs),
        text content for text files, or JSON with error field if not found.

    Examples:
        - retrieve_file(message_id="msg-abc123", file_index=0) - Get first file from message
        - retrieve_file(message_id="msg-abc123") - Same as above (file_index defaults to 0)

    After retrieving an image, you can pass it to generate_image using:
        generate_image(prompt="...", history_image_message_id="msg-abc123", history_image_file_index=0)
    """
    # Import here to avoid circular imports
    from src.db.blob_store import get_blob_store
    from src.db.models import db, make_blob_key

    conv_id, user_id = get_conversation_context()

    if not conv_id or not user_id:
        logger.warning("retrieve_file called without conversation context")
        return json.dumps(
            {
                "error": "No conversation context available. This tool can only be used during a chat."
            }
        )

    # Verify user owns the conversation
    conv = db.get_conversation(conv_id, user_id)
    if not conv:
        logger.warning(
            "retrieve_file: conversation not found or not authorized",
            extra={"conv_id": conv_id, "user_id": user_id},
        )
        return json.dumps({"error": "Conversation not found or not authorized."})

    logger.info(
        "retrieve_file: retrieving file",
        extra={
            "conv_id": conv_id,
            "message_id": message_id,
            "file_index": file_index,
        },
    )

    # Get the message
    message = db.get_message_by_id(message_id)
    if not message:
        logger.warning(
            "retrieve_file: message not found",
            extra={"message_id": message_id},
        )
        return json.dumps({"error": f"Message not found: {message_id}"})

    # Verify message belongs to this conversation
    if message.conversation_id != conv_id:
        logger.warning(
            "retrieve_file: message belongs to different conversation",
            extra={
                "message_id": message_id,
                "message_conv_id": message.conversation_id,
                "current_conv_id": conv_id,
            },
        )
        return json.dumps({"error": "Message does not belong to this conversation."})

    # Check file exists
    if not message.files or file_index >= len(message.files):
        logger.warning(
            "retrieve_file: file not found",
            extra={
                "message_id": message_id,
                "file_index": file_index,
                "file_count": len(message.files) if message.files else 0,
            },
        )
        return json.dumps(
            {
                "error": f"File index {file_index} not found in message. Message has {len(message.files) if message.files else 0} file(s)."
            }
        )

    file_meta = message.files[file_index]
    file_name = file_meta.get("name", f"file_{file_index}")
    mime_type = file_meta.get("type", "application/octet-stream")

    # Age-based retention gate: stays truthful even before the physical
    # sweep has deleted the blob (videos 7 days, images 30 days)
    from src.utils.file_retention import is_file_expired, retention_note

    if is_file_expired(mime_type, message.created_at):
        return json.dumps(
            {
                "error": f"This file has been cleaned up and is no longer available. "
                f"{retention_note(mime_type)}."
            }
        )

    # Get file data from blob store
    blob_store = get_blob_store()
    blob_key = make_blob_key(message_id, file_index)
    blob_result = blob_store.get(blob_key)

    if blob_result:
        binary_data, stored_mime_type = blob_result
        # Use stored MIME type if available
        if stored_mime_type:
            mime_type = stored_mime_type
    else:
        # Fall back to legacy base64 data in message
        if "data" in file_meta:
            try:
                binary_data = base64.b64decode(file_meta["data"])
            except Exception:
                logger.error(
                    "retrieve_file: failed to decode legacy base64 data",
                    extra={"message_id": message_id, "file_index": file_index},
                )
                return json.dumps({"error": "Failed to read file data."})
        else:
            logger.warning(
                "retrieve_file: no file data found",
                extra={"message_id": message_id, "file_index": file_index},
            )
            return json.dumps({"error": "File data not found in storage."})

    logger.info(
        "retrieve_file: file retrieved successfully",
        extra={
            "message_id": message_id,
            "file_index": file_index,
            "file_name": file_name,
            "mime_type": mime_type,
            "size": len(binary_data),
        },
    )
    return _build_file_content(message_id, file_index, file_name, mime_type, binary_data)


def _build_file_content(
    message_id: str,
    file_index: int,
    file_name: str,
    mime_type: str,
    binary_data: bytes,
) -> str | list[dict[str, Any]]:
    """Turn retrieved file bytes into tool content the chat model can consume.

    Everything returned here is sent inline on every later model call in the
    turn, so it must stay well under Gemini's ~20 MB inline request limit.
    """
    file_size = len(binary_data)
    header = f"Here is {file_name} ({mime_type}, {file_size} bytes) from message {message_id}:"

    # Analysis doesn't need more than ~2K pixels; shrinks 4K generations ~10x
    if mime_type.startswith("image/"):
        binary_data, mime_type = downscale_image_for_reference(binary_data, mime_type)

    is_visual = mime_type.startswith("image/") or mime_type == "application/pdf"
    too_big_inline = len(binary_data) > Config.GEMINI_INLINE_FILE_MAX_BYTES

    # Videos always, and oversized images/PDFs, go via the Gemini Files API;
    # skip the base64 encoding - a 100MB video would be needlessly inflated
    if mime_type.startswith("video/") or (is_visual and too_big_inline):
        from src.agent.gemini_files import GeminiFileError, ensure_gemini_file_uri

        kind = "video" if mime_type.startswith("video/") else "file"
        try:
            uri = ensure_gemini_file_uri(message_id, file_index, binary_data, mime_type)
        except GeminiFileError as e:
            return json.dumps({"error": f"Failed to prepare {kind} for viewing: {e}"})
        logger.info(
            "retrieve_file: file prepared via Files API",
            extra={"message_id": message_id, "file_index": file_index, "mime_type": mime_type},
        )
        return [
            {"type": "text", "text": header},
            {"type": "media", "file_uri": uri, "mime_type": mime_type},
        ]

    if is_visual:
        return [
            {"type": "text", "text": header},
            {
                "type": "image",  # LangChain uses "image" type for both images and PDFs
                "base64": base64.b64encode(binary_data).decode("utf-8"),
                "mime_type": mime_type,
            },
        ]

    # For text files, decode and return as (capped) text
    if mime_type.startswith("text/") or mime_type in (
        "application/json",
        "application/xml",
    ):
        try:
            text_content = binary_data.decode("utf-8")
        except UnicodeDecodeError:
            pass  # Fall through to the metadata-only return
        else:
            max_chars = Config.RETRIEVE_FILE_TEXT_MAX_CHARS
            if len(text_content) > max_chars:
                text_content = (
                    f"{text_content[:max_chars]}\n\n[... truncated: showing the first "
                    f"{max_chars} of {len(text_content)} characters]"
                )
            return f"Here is the content of {file_name} ({mime_type}):\n\n{text_content}"

    # Other binary files: base64 as text is unreadable to the model and costs
    # tokens proportional to size, so return metadata only
    return json.dumps(
        {
            "success": True,
            "file": {
                "message_id": message_id,
                "file_index": file_index,
                "name": file_name,
                "type": mime_type,
                "size": file_size,
            },
            "note": "Binary file content cannot be shown directly.",
        }
    )
