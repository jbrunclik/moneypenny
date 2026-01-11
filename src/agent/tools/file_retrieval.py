"""File retrieval tool for accessing files from conversation history."""

import base64
import json
from typing import Any

from langchain_core.tools import tool

from src.agent.tools.context import get_conversation_context
from src.utils.logging import get_logger

logger = get_logger(__name__)


@tool
def retrieve_file(
    message_id: str | None = None,
    file_index: int = 0,
    list_files: bool = False,
) -> str | list[dict[str, Any]]:
    """Retrieve a file from conversation history or list all available files.

    Use this tool to:
    - List all files in the conversation to see what's available
    - Retrieve a specific file by message_id and file_index for analysis
    - Get images from earlier messages to use with generate_image as references

    Args:
        message_id: The message ID containing the file. Required unless list_files=True.
        file_index: Index of the file in the message (0-based, default 0).
        list_files: If True, returns a list of all files in the conversation.
                   Ignores message_id and file_index when True.

    Returns:
        For list_files=True: JSON with files array containing message_id, file_index,
                            name, type, and size for each file.
        For file retrieval: Multimodal content with the file data for analysis,
                           or JSON with error field if not found.

    Examples:
        - retrieve_file(list_files=True) - List all files in conversation
        - retrieve_file(message_id="msg-abc123", file_index=0) - Get first file from message
        - retrieve_file(message_id="msg-abc123") - Same as above (file_index defaults to 0)

    After retrieving an image, you can pass it to generate_image using:
        generate_image(prompt="...", retrieved_file_message_id="msg-abc123", retrieved_file_index=0)
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

    # List all files in conversation
    if list_files:
        logger.info(
            "retrieve_file: listing files",
            extra={"conv_id": conv_id, "user_id": user_id},
        )
        messages = db.get_messages(conv_id)
        all_files: list[dict[str, Any]] = []

        for msg in messages:
            if msg.files:
                for idx, file in enumerate(msg.files):
                    all_files.append(
                        {
                            "message_id": msg.id,
                            "file_index": idx,
                            "name": file.get("name", f"file_{idx}"),
                            "type": file.get("type", "application/octet-stream"),
                            "size": file.get("size", 0),
                            "role": msg.role.value,  # user or assistant
                        }
                    )

        logger.info(
            "retrieve_file: found files",
            extra={"conv_id": conv_id, "file_count": len(all_files)},
        )
        return json.dumps(
            {
                "files": all_files,
                "count": len(all_files),
                "message": f"Found {len(all_files)} file(s) in conversation."
                if all_files
                else "No files found in conversation.",
            }
        )

    # Retrieve specific file
    if not message_id:
        return json.dumps(
            {
                "error": "message_id is required to retrieve a file. Use list_files=True to see available files."
            }
        )

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
    file_size = file_meta.get("size", 0)

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

    # Encode as base64 for return
    file_base64 = base64.b64encode(binary_data).decode("utf-8")
    file_size = len(binary_data)

    logger.info(
        "retrieve_file: file retrieved successfully",
        extra={
            "message_id": message_id,
            "file_index": file_index,
            "file_name": file_name,
            "mime_type": mime_type,
            "size": file_size,
        },
    )

    # For images and PDFs, return multimodal content for analysis
    if mime_type.startswith("image/") or mime_type == "application/pdf":
        return [
            {
                "type": "text",
                "text": f"Here is {file_name} ({mime_type}, {file_size} bytes) from message {message_id}:",
            },
            {
                "type": "image",  # LangChain uses "image" type for both images and PDFs
                "base64": file_base64,
                "mime_type": mime_type,
            },
        ]

    # For text files, decode and return as text
    if mime_type.startswith("text/") or mime_type in (
        "application/json",
        "application/xml",
    ):
        try:
            text_content = binary_data.decode("utf-8")
            return f"Here is the content of {file_name} ({mime_type}):\n\n{text_content}"
        except UnicodeDecodeError:
            pass  # Fall through to base64 return

    # For other files, return metadata with base64
    return json.dumps(
        {
            "success": True,
            "file": {
                "message_id": message_id,
                "file_index": file_index,
                "name": file_name,
                "type": mime_type,
                "size": file_size,
                "data": file_base64,
            },
        }
    )
