"""Conversation history enrichment with temporal context.

This module enriches conversation history before passing to the LLM,
adding timestamps, session gap indicators, file metadata, and tool summaries.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

from src.config import Config
from src.db.models.dataclasses import Message


class FileMetadata(TypedDict):
    """File metadata for direct tool access."""

    name: str
    type: str  # Simplified type: "image", "PDF", "text file", etc.
    message_id: str
    file_index: int


class MessageMetadata(TypedDict, total=False):
    """Structured metadata for enriched history messages."""

    timestamp: str  # Absolute with timezone: "2024-06-15 14:30 CET"
    relative_time: str  # Relative: "5 minutes ago", "2 days ago"
    session_gap: str | None  # "6 hours", "2 days" or None
    files: list[FileMetadata] | None  # With message_id for direct access
    tools_used: list[str] | None  # ["web_search", "generate_image"]
    tool_summary: str | None  # "searched 3 sources, generated 1 image"


class EnrichedMessage(TypedDict):
    """A history message with structured metadata."""

    role: str
    content: str
    metadata: MessageMetadata


def format_timestamp(dt: datetime) -> str:
    """Format a datetime as an absolute timestamp with timezone.

    Args:
        dt: The datetime to format

    Returns:
        Formatted string like "2024-06-15 14:30 CET"
    """
    # Get timezone abbreviation from the local timezone
    local_tz = datetime.now().astimezone().tzinfo
    if dt.tzinfo is None:
        # Assume naive datetimes are in local time
        dt = dt.replace(tzinfo=local_tz)
    elif dt.tzinfo == UTC:
        # Convert UTC to local time
        dt = dt.astimezone(local_tz)

    # Format: "2024-06-15 14:30 CET"
    tz_name = dt.strftime("%Z") or "UTC"
    return dt.strftime(f"%Y-%m-%d %H:%M {tz_name}")


def format_relative_time(dt: datetime, now: datetime | None = None) -> str:
    """Format a datetime as a relative time string.

    Args:
        dt: The datetime to format
        now: The current time (defaults to now)

    Returns:
        Relative time like "5 minutes ago", "2 days ago"
    """
    if now is None:
        now = datetime.now()

    # Handle timezone-aware datetimes
    if dt.tzinfo is not None and now.tzinfo is None:
        now = now.astimezone()
    elif dt.tzinfo is None and now.tzinfo is not None:
        dt = dt.replace(tzinfo=now.tzinfo)

    delta = now - dt

    seconds = delta.total_seconds()
    if seconds < 0:
        return "just now"

    minutes = seconds / 60
    if minutes < 1:
        return "just now"
    if minutes < 2:
        return "1 minute ago"
    if minutes < 60:
        return f"{int(minutes)} minutes ago"

    hours = minutes / 60
    if hours < 2:
        return "1 hour ago"
    if hours < 24:
        return f"{int(hours)} hours ago"

    days = hours / 24
    if days < 2:
        return "1 day ago"
    if days < 7:
        return f"{int(days)} days ago"

    weeks = days / 7
    if weeks < 2:
        return "1 week ago"
    return f"{int(weeks)} weeks ago"


def detect_session_gap(prev_msg: Message, curr_msg: Message) -> timedelta | None:
    """Detect if there's a session gap between two messages.

    Args:
        prev_msg: The previous message in the conversation
        curr_msg: The current message

    Returns:
        The gap duration if it exceeds the threshold, None otherwise
    """
    gap = curr_msg.created_at - prev_msg.created_at
    threshold = timedelta(hours=Config.HISTORY_SESSION_GAP_HOURS)

    if gap >= threshold:
        return gap
    return None


def format_session_gap(gap: timedelta) -> str:
    """Format a session gap duration as a human-readable string.

    Args:
        gap: The gap timedelta

    Returns:
        Formatted string like "6 hours", "2 days"
    """
    hours = gap.total_seconds() / 3600

    if hours < 24:
        if hours < 2:
            return "1 hour"
        return f"{int(hours)} hours"

    days = hours / 24
    if days < 2:
        return "1 day"
    return f"{int(days)} days"


def simplify_mime_type(mime_type: str) -> str:
    """Simplify a MIME type to a user-friendly description.

    Args:
        mime_type: The MIME type (e.g., "image/png", "application/pdf")

    Returns:
        Simplified description like "image", "PDF", "text file"
    """
    if mime_type.startswith("image/"):
        return "image"
    if mime_type == "application/pdf":
        return "PDF"
    if mime_type.startswith("text/"):
        ext_map = {
            "text/plain": "text file",
            "text/markdown": "Markdown",
            "text/csv": "CSV",
        }
        return ext_map.get(mime_type, "text file")
    if mime_type == "application/json":
        return "JSON"
    return "file"


def format_file_metadata(msg: Message) -> list[FileMetadata] | None:
    """Extract file metadata from a message for context.

    Args:
        msg: The message containing file attachments

    Returns:
        List of file metadata dicts, or None if no files
    """
    if not msg.files:
        return None

    files: list[FileMetadata] = []
    for idx, file in enumerate(msg.files):
        name = file.get("name", f"file_{idx}")
        mime_type = file.get("type", "application/octet-stream")
        files.append(
            FileMetadata(
                name=name,
                type=simplify_mime_type(mime_type),
                message_id=msg.id,
                file_index=idx,
            )
        )

    return files if files else None


def infer_tools_used(
    sources: list[dict[str, str]] | None, generated_images: list[dict[str, str]] | None
) -> list[str]:
    """Infer which tools were used based on message metadata.

    Args:
        sources: List of web sources from the message
        generated_images: List of generated image metadata

    Returns:
        List of tool names that were used
    """
    tools: list[str] = []

    if sources:
        tools.append("web_search")
    if generated_images:
        tools.append("generate_image")

    return tools


def format_tool_summary(
    sources: list[dict[str, str]] | None, generated_images: list[dict[str, str]] | None
) -> str | None:
    """Format a summary of tools used in an assistant message.

    Args:
        sources: List of web sources from the message
        generated_images: List of generated image metadata

    Returns:
        Summary string like "searched 3 sources, generated 1 image", or None
    """
    parts: list[str] = []

    if sources:
        count = len(sources)
        if count == 1:
            parts.append("searched 1 web source")
        else:
            parts.append(f"searched {count} web sources")

    if generated_images:
        count = len(generated_images)
        if count == 1:
            parts.append("generated 1 image")
        else:
            parts.append(f"generated {count} images")

    return ", ".join(parts) if parts else None


def enrich_history(messages: list[Message]) -> list[dict[str, Any]]:
    """Enrich conversation history with temporal context and metadata.

    Args:
        messages: List of Message objects from the database

    Returns:
        List of enriched message dicts with metadata
    """
    if not messages:
        return []

    enriched: list[dict[str, Any]] = []
    now = datetime.now()
    prev_msg: Message | None = None

    for msg in messages:
        # Build base metadata
        metadata: MessageMetadata = {
            "timestamp": format_timestamp(msg.created_at),
            "relative_time": format_relative_time(msg.created_at, now),
        }

        # Check for session gap
        if prev_msg is not None:
            gap = detect_session_gap(prev_msg, msg)
            if gap is not None:
                metadata["session_gap"] = format_session_gap(gap)

        # Add role-specific metadata
        if msg.role.value == "user":
            files = format_file_metadata(msg)
            if files:
                metadata["files"] = files
        elif msg.role.value == "assistant":
            tools_used = infer_tools_used(msg.sources, msg.generated_images)
            if tools_used:
                metadata["tools_used"] = tools_used

            tool_summary = format_tool_summary(msg.sources, msg.generated_images)
            if tool_summary:
                metadata["tool_summary"] = tool_summary

        enriched.append(
            {
                "role": msg.role.value,
                "content": msg.content,
                "metadata": metadata,
            }
        )

        prev_msg = msg

    return enriched
