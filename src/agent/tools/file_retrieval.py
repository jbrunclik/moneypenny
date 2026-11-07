"""File retrieval tool for accessing files from conversation history."""

import base64
import json
from typing import Any

from langchain_core.tools import tool

from src.agent.gemini_files import GeminiFileError, ensure_gemini_file_uri
from src.agent.tools.conversation_files import load_conversation_file
from src.agent.tools.errors import tool_error
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
    loaded = load_conversation_file(message_id, file_index)
    if isinstance(loaded, str):
        return loaded
    return _build_file_content(message_id, file_index, loaded.name, loaded.mime_type, loaded.data)


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
        kind = "video" if mime_type.startswith("video/") else "file"
        try:
            uri = ensure_gemini_file_uri(message_id, file_index, binary_data, mime_type)
        except GeminiFileError as e:
            return tool_error(f"Failed to prepare {kind} for viewing: {e}")
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
