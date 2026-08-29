"""Attachment tool.

Lets the LLM hand the user a downloadable file without running code. The model
writes the complete file contents itself (e.g. a Rouvy/Zwift ``.zwo`` workout,
a ``.csv``, an ``.ics`` calendar, a ``.gpx`` route) and this tool turns them into
a message attachment via the same ``_full_result.files`` pipeline that
``execute_code`` and ``generate_image`` use.

This exists so context-lean conversations (e.g. the sports trainer, which drops
``execute_code`` to save ~7k tokens/round) can still produce downloadable files.
Only text-based files are supported - there is no code execution here.
"""

import base64
import json
import mimetypes
import os

from langchain_core.tools import tool

from src.utils.logging import get_logger

logger = get_logger(__name__)

# Cap the file size: the content lands in LLM context as-is on the tool call and
# is base64-encoded into the message, so an unbounded file would blow up cost.
MAX_ATTACHMENT_BYTES = 1_000_000

# Extensions the stdlib mimetypes module does not know about. ZWO (Zwift/Rouvy
# structured workouts) is XML under the hood.
_EXTRA_MIME_TYPES = {
    ".zwo": "application/xml",
    ".gpx": "application/gpx+xml",
    ".fit": "application/octet-stream",
}


def _guess_mime_type(filename: str) -> str:
    """Resolve a MIME type from the filename, covering fitness formats too."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in _EXTRA_MIME_TYPES:
        return _EXTRA_MIME_TYPES[ext]
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


@tool
def create_file(filename: str, content: str, mime_type: str | None = None) -> str:
    """Attach a downloadable text file to your reply for the user.

    Use this to hand the user a file they can download - for example a Rouvy/Zwift
    ``.zwo`` workout file, a ``.csv`` table, an ``.ics`` calendar invite, a ``.gpx``
    route, an ``.svg`` image, or any other text-based format. Write the complete
    file contents yourself and pass them as ``content``; the file is attached to
    your response for the user to download.

    This does NOT run any code - author the file contents directly. For binary
    output or files that require computation, use ``execute_code`` instead (when
    available).

    Args:
        filename: File name including extension, e.g. "workout.zwo" or "plan.csv".
        content: The complete text content of the file.
        mime_type: Optional MIME type. If omitted, it is guessed from the
            extension (with fitness formats like .zwo/.gpx handled explicitly).

    Returns:
        JSON describing the created file. The file data rides in a ``_full_result``
        field that is stripped before reaching you and surfaced to the user as a
        downloadable attachment.
    """
    # Keep only the base name so the model cannot smuggle a path into the filename.
    safe_name = os.path.basename(filename or "").strip()
    if not safe_name:
        return json.dumps({"success": False, "error": "filename must not be empty."})

    if not content:
        return json.dumps({"success": False, "error": "content must not be empty."})

    data = content.encode("utf-8")
    if len(data) > MAX_ATTACHMENT_BYTES:
        return json.dumps(
            {
                "success": False,
                "error": (
                    f"content is too large ({len(data)} bytes); "
                    f"the limit is {MAX_ATTACHMENT_BYTES} bytes."
                ),
            }
        )

    resolved_mime = (
        mime_type.strip() if mime_type and mime_type.strip() else _guess_mime_type(safe_name)
    )
    encoded = base64.b64encode(data).decode("ascii")

    logger.info(
        "create_file attachment produced",
        extra={"file_name": safe_name, "mime_type": resolved_mime, "size": len(data)},
    )

    return json.dumps(
        {
            "success": True,
            # LLM-visible metadata only - the base64 payload is stripped from context.
            "file": {"name": safe_name, "mime_type": resolved_mime, "size": len(data)},
            "message": (
                f"Created {safe_name} ({len(data)} bytes). "
                "It is attached to your reply for the user to download."
            ),
            "_full_result": {
                "files": [
                    {
                        "name": safe_name,
                        "mime_type": resolved_mime,
                        "data": encoded,
                        "size": len(data),
                    }
                ]
            },
        }
    )
