"""LangChain message content for ChatAgent turns.

Turns stored/enriched chat messages into what the model sees: multimodal
content blocks for attachments, and the MSG_CONTEXT metadata prefix for
history messages.
"""

import base64
import binascii
import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


def _file_block(file: dict[str, Any]) -> dict[Any, Any] | None:
    """Content block for one attachment, or None when it cannot be decoded."""
    mime_type = file.get("type", "application/octet-stream")
    data = file.get("data", "")

    if mime_type.startswith("image/"):
        # Image block for Gemini
        return {
            "type": "image",
            "base64": data,
            "mime_type": mime_type,
        }
    if mime_type.startswith("video/"):
        # Videos go via the Gemini Files API (inline limit is ~20MB).
        # The URI is attached by attach_gemini_file_uris() before the
        # agent runs; absence means the upload failed.
        uri = file.get("gemini_file_uri")
        if uri:
            return {"type": "media", "file_uri": uri, "mime_type": mime_type}
        error = file.get("gemini_upload_error", "processing failed")
        name = file.get("name", "video")
        return {
            "type": "text",
            "text": f"[Video '{name}' could not be attached: {error}. "
            "Tell the user the video could not be processed.]",
        }
    if mime_type == "application/pdf":
        # PDF - Gemini supports inline PDFs
        return {
            "type": "image",  # LangChain uses image type for PDFs too
            "base64": data,
            "mime_type": mime_type,
        }
    # Text files - include as text block
    try:
        decoded = base64.b64decode(data).decode("utf-8")
    except binascii.Error, UnicodeDecodeError:
        # If decoding fails (invalid base64 or non-UTF-8), skip the file
        return None
    file_name = file.get("name", "file")
    return {
        "type": "text",
        "text": f"\n--- Content of {file_name} ---\n{decoded}\n--- End of {file_name} ---\n",
    }


def build_message_content(
    text: str, files: list[dict[str, Any]] | None = None
) -> str | list[str | dict[Any, Any]]:
    """Build message content for LangChain.

    Args:
        text: Plain text message
        files: Optional list of file attachments

    Returns:
        For text-only: the string
        For multimodal: list of content blocks for LangChain
    """
    if not files:
        return text

    # Build multimodal content blocks
    blocks: list[str | dict[Any, Any]] = []

    # Add text block if present
    if text:
        blocks.append({"type": "text", "text": text})

    # Add file blocks
    for file in files:
        block = _file_block(file)
        if block is not None:
            blocks.append(block)

    return blocks if blocks else text


def format_message_with_metadata(msg: dict[str, Any]) -> str:
    """Format message content with metadata context for LLM.

    Enriches message content with temporal context, file references,
    and tool usage summaries as a JSON metadata block. Uses a distinct
    <!-- MSG_CONTEXT: --> marker (different from response <!-- METADATA: -->)
    to prevent the LLM from echoing this format in its responses.

    Args:
        msg: Enriched message dict with 'role', 'content', and 'metadata' keys

    Returns:
        Formatted string with JSON metadata block prefixed to content
    """
    metadata = msg.get("metadata", {})
    content: str = msg["content"]

    # Build compact metadata dict with only present fields
    meta_dict: dict[str, Any] = {}

    # Session gap indicator (if present)
    if metadata.get("session_gap"):
        meta_dict["session_gap"] = metadata["session_gap"]

    # Timestamps (absolute only — a recomputed relative time would change
    # the serialized bytes every turn and defeat history prefix caching)
    if metadata.get("timestamp"):
        meta_dict["timestamp"] = metadata["timestamp"]

    # Files (for user messages) - compact format for direct tool access
    if metadata.get("files"):
        meta_dict["files"] = [
            {
                "name": f["name"],
                "type": f["type"],
                "id": f"{f['message_id']}:{f['file_index']}",
                **({"expired": True} if f.get("expired") else {}),
            }
            for f in metadata["files"]
        ]

    # Tool usage (for assistant messages)
    if metadata.get("tools_used"):
        meta_dict["tools_used"] = metadata["tools_used"]
    if metadata.get("tool_summary"):
        meta_dict["tool_summary"] = metadata["tool_summary"]
    # Which exact sources the turn read (title + URL) - lets follow-ups
    # like "what did that article say?" re-fetch precisely instead of
    # re-running searches. Derived from persisted sources, so the
    # serialized bytes are stable across turns (prefix-cache safe).
    if metadata.get("tool_digest"):
        meta_dict["tool_digest"] = metadata["tool_digest"]
    # Head of each non-web tool result from that turn (Garmin, Todoist,
    # kv_store, code...) - raw ToolMessages are gone by the next turn, so
    # this is what lets "what was my HRV again?" skip re-calling the tool
    if metadata.get("tool_outputs"):
        meta_dict["tool_outputs"] = metadata["tool_outputs"]
    # Claims of that answer the grounding check found unsourced or
    # contradicted - a follow-up must not restate them as fact
    if metadata.get("grounding"):
        meta_dict["grounding"] = metadata["grounding"]
    # The reply is a deep-research report: follow-ups can use it as is
    if metadata.get("research"):
        meta_dict["research"] = metadata["research"]

    # Return with metadata block if we have any metadata
    # Use MSG_CONTEXT marker (distinct from response METADATA) to prevent echoing
    if meta_dict:
        # ensure_ascii=False: Czech file names/summaries as real characters
        # (escapes waste tokens and can be echoed back by the model)
        json_str = json.dumps(meta_dict, separators=(",", ":"), ensure_ascii=False)
        return f"<!-- MSG_CONTEXT: {json_str} -->\n{content}"
    return content


def history_to_messages(history: list[dict[str, Any]]) -> list[BaseMessage]:
    """LangChain messages for enriched history dicts (user/assistant only)."""
    messages: list[BaseMessage] = []
    for msg in history:
        # Format content with metadata context (timestamps, files, tools)
        formatted_content = format_message_with_metadata(msg)

        if msg["role"] == "user":
            # User messages may have file attachments (handled separately)
            content = build_message_content(formatted_content, msg.get("files"))
            messages.append(HumanMessage(content=content))
        elif msg["role"] == "assistant":
            # Assistant messages are always text
            messages.append(AIMessage(content=formatted_content))
    return messages
