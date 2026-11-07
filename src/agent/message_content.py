"""LangChain message content for ChatAgent turns.

Turns stored/enriched chat messages into what the model sees: multimodal
content blocks for attachments, and the MSG_CONTEXT metadata prefix for
history messages.
"""

import base64
import binascii
import json
from collections.abc import Iterable, Mapping
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from src.utils.files import UploadedFile


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
    if listing := _file_id_listing(files):
        blocks.append({"type": "text", "text": listing})

    return blocks if blocks else text


def annotate_history_file_ids(message_id: str, files: list[UploadedFile]) -> None:
    """Give a just-saved message's uploads their history ids (transient).

    History turns list files as ``message_id:file_index``; the current message
    sends them inline, without one - so the code sandbox could not open a file
    attached to this very message (execute_code(files=...) takes the id).
    """
    for index, file in enumerate(files):
        file["history_file_id"] = f"{message_id}:{index}"


def _file_id_listing(files: Iterable[Mapping[str, object]]) -> str | None:
    """A line naming each upload's id, when they have one."""
    named = [
        f"{f.get('name', 'file')} (id {f['history_file_id']})"
        for f in files
        if f.get("history_file_id")
    ]
    if not named:
        return None
    return (
        f"[Files attached to this message: {', '.join(named)}. To measure, parse or convert "
        "one in code, pass its id to execute_code(files=[...]).]"
    )


# Assistant-message fields copied into MSG_CONTEXT as is, in this order
_ASSISTANT_CONTEXT_KEYS = (
    # Tool usage
    "tools_used",
    "tool_summary",
    # Which exact sources the turn read (title + URL) - lets follow-ups
    # like "what did that article say?" re-fetch precisely instead of
    # re-running searches. Derived from persisted sources, so the
    # serialized bytes are stable across turns (prefix-cache safe).
    "tool_digest",
    # Head of each non-web tool result from that turn (Garmin, Todoist,
    # kv_store, code...) - raw ToolMessages are gone by the next turn, so
    # this is what lets "what was my HRV again?" skip re-calling the tool
    "tool_outputs",
    # Claims of that answer the grounding check found unsourced or
    # contradicted - a follow-up must not restate them as fact
    "grounding",
    # The reply is a deep-research report: follow-ups can use it as is
    "research",
    # Artifacts under this reply: update_artifact / read_artifact take these ids
    "artifacts",
)


def _compact_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """User-message files in the compact form tools address them by."""
    return [
        {
            "name": f["name"],
            "type": f["type"],
            "id": f"{f['message_id']}:{f['file_index']}",
            **({"expired": True} if f.get("expired") else {}),
        }
        for f in files
    ]


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

    # Session gap indicator, then the timestamp (absolute only — a recomputed
    # relative time would change the serialized bytes every turn and defeat
    # history prefix caching)
    for key in ("session_gap", "timestamp"):
        if metadata.get(key):
            meta_dict[key] = metadata[key]

    # Files (for user messages) - compact format for direct tool access
    if metadata.get("files"):
        meta_dict["files"] = _compact_files(metadata["files"])

    for key in _ASSISTANT_CONTEXT_KEYS:
        if metadata.get(key):
            meta_dict[key] = metadata[key]

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
