"""LangChain message content for ChatAgent turns.

Turns stored/enriched chat messages into what the model sees: multimodal
content blocks for attachments, and the MSG_CONTEXT metadata prefix for
history messages.
"""

import base64
import binascii
import json
import time
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from src.utils.files import UploadedFile, gemini_mime_type, is_media_mime
from src.utils.logging import get_logger
from src.utils.office_text import OFFICE_KINDS, OfficeReadError, office_text

logger = get_logger(__name__)


def office_text_for_model(name: str, mime_type: str, data: bytes, file_id: str | None) -> str:
    """An Office file's text for the model, or a notice saying why it cannot be read.

    Never raises: an unreadable upload must not fail the turn.
    """
    started = time.monotonic()
    kind = OFFICE_KINDS[mime_type]
    open_in_code = f"execute_code(files=['{file_id}'])" if file_id else "execute_code"
    try:
        result = office_text(data, mime_type)
    except OfficeReadError as e:
        _log_office(mime_type, 0, truncated=False, started=started, error=str(e))
        return (
            f"[{name} could not be read as text: {e}. "
            f"Its original can still be opened with {open_in_code}.]"
        )
    _log_office(mime_type, len(result.text), result.truncated, started)
    cut = (
        f"\n[... truncated at {len(result.text)} characters; open the whole file with {open_in_code}]"
        if result.truncated
        else ""
    )
    return f"\n--- Content of {name} ({kind}) ---\n{result.text}{cut}\n--- End of {name} ---\n"


def _log_office(
    mime_type: str, chars: int, truncated: bool, started: float, error: str | None = None
) -> None:
    logger.info(
        "office text extracted",
        extra={
            "type": OFFICE_KINDS[mime_type],
            "chars": chars,
            "truncated": truncated,
            "ms": round((time.monotonic() - started) * 1000),
            "error": error,
        },
    )


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
    if is_media_mime(mime_type):
        # Video and audio go via the Gemini Files API (inline limit is ~20MB).
        # The URI is attached by attach_gemini_file_uris() before the
        # agent runs; absence means the upload failed.
        uri = file.get("gemini_file_uri")
        if uri:
            return {"type": "media", "file_uri": uri, "mime_type": gemini_mime_type(mime_type)}
        error = file.get("gemini_upload_error", "processing failed")
        kind = "Video" if mime_type.startswith("video/") else "Audio"
        name = file.get("name", kind.lower())
        return {
            "type": "text",
            "text": f"[{kind} '{name}' could not be attached: {error}. "
            f"Tell the user the {kind.lower()} could not be processed.]",
        }
    if mime_type == "application/pdf":
        # PDF - Gemini supports inline PDFs
        return {
            "type": "image",  # LangChain uses image type for PDFs too
            "base64": data,
            "mime_type": mime_type,
        }
    if mime_type in OFFICE_KINDS:
        try:
            raw = base64.b64decode(data)
        except binascii.Error:
            return None
        name = file.get("name", "document")
        text = office_text_for_model(name, mime_type, raw, file.get("history_file_id"))
        return {"type": "text", "text": text}
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


def attachment_count(files: Sequence[Mapping[str, object]] | None) -> int:
    """The attachments the model receives as images, PDFs or media - not as text."""
    return sum(
        1
        for f in files or []
        if (mime := str(f.get("type", ""))).startswith("image/")
        or mime == "application/pdf"
        or is_media_mime(mime)
    )


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
        "one in code, pass its id to execute_code(files=[...]); to keep one in the user's "
        "saved documents, pass it as file_id to manage_documents.]"
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
    """A message's files (uploads, or the agent's own outputs) in the compact form tools address them by."""
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

    # Files (uploads, and a reply's own outputs) - compact format for direct tool access
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
