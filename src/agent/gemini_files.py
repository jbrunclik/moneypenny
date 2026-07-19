"""Bridge to the Gemini Files API for large media (videos).

Gemini's inline generateContent limit is ~20MB, so videos are uploaded to
the Files API and referenced by file_uri. Uploaded files live 48h on
Google's side; we cache the URI in kv_store for 47h and re-upload on demand.
"""

import base64
import binascii
import io
import json
import time
from datetime import timedelta
from typing import Any

from google import genai
from google.genai import types as genai_types

from src.config import Config
from src.db.models import db
from src.utils.datetime_utils import utcnow_naive
from src.utils.logging import get_logger

logger = get_logger(__name__)

GEMINI_FILES_NAMESPACE = "gemini_files"
SYSTEM_KV_USER_ID = "_system"
CACHE_TTL_HOURS = 47  # Gemini keeps files 48h; refresh one hour early
POLL_INTERVAL_SECONDS = 2
PROCESSING_TIMEOUT_SECONDS = 120


class GeminiFileError(Exception):
    """Raised when uploading or processing a file via the Files API fails."""


def _get_client() -> genai.Client:
    return genai.Client(api_key=Config.GEMINI_API_KEY)


def _cache_key(message_id: str, file_index: int) -> str:
    return f"{message_id}:{file_index}"


def _get_cached_uri(message_id: str, file_index: int) -> str | None:
    raw = db.kv_get(SYSTEM_KV_USER_ID, GEMINI_FILES_NAMESPACE, _cache_key(message_id, file_index))
    if not raw:
        return None
    try:
        entry = json.loads(raw)
        if utcnow_naive().isoformat() < entry["expires_at"]:
            return str(entry["uri"])
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return None


def ensure_gemini_file_uri(message_id: str, file_index: int, data: bytes, mime_type: str) -> str:
    """Return an ACTIVE Gemini Files API URI for this file, uploading if needed.

    Raises:
        GeminiFileError: if upload or server-side processing fails.
    """
    cached = _get_cached_uri(message_id, file_index)
    if cached:
        logger.debug(
            "Gemini file URI cache hit",
            extra={"message_id": message_id, "file_index": file_index},
        )
        return cached

    client = _get_client()
    logger.info(
        "Uploading file to Gemini Files API",
        extra={
            "message_id": message_id,
            "file_index": file_index,
            "mime_type": mime_type,
            "size": len(data),
        },
    )

    def _state_name(f: Any) -> str:
        return f.state.name if f.state else "UNKNOWN"

    try:
        gfile = client.files.upload(
            file=io.BytesIO(data),
            config=genai_types.UploadFileConfig(mime_type=mime_type),
        )
        deadline = time.monotonic() + PROCESSING_TIMEOUT_SECONDS
        while _state_name(gfile) == "PROCESSING":
            if time.monotonic() > deadline:
                raise GeminiFileError("Timed out waiting for Gemini to process the file")
            time.sleep(POLL_INTERVAL_SECONDS)
            if not gfile.name:
                raise GeminiFileError("Gemini file upload returned no file name")
            gfile = client.files.get(name=gfile.name)
    except GeminiFileError:
        raise
    except Exception as e:
        raise GeminiFileError(f"Gemini Files API upload failed: {e}") from e

    if _state_name(gfile) != "ACTIVE":
        raise GeminiFileError(f"Gemini file processing failed (state: {_state_name(gfile)})")

    expires_at = (utcnow_naive() + timedelta(hours=CACHE_TTL_HOURS)).isoformat()
    if not gfile.uri:
        raise GeminiFileError("Gemini returned an ACTIVE file without a URI")

    db.kv_set(
        SYSTEM_KV_USER_ID,
        GEMINI_FILES_NAMESPACE,
        _cache_key(message_id, file_index),
        json.dumps({"uri": gfile.uri, "name": gfile.name, "expires_at": expires_at}),
    )
    return str(gfile.uri)


def attach_gemini_file_uris(message_id: str, files: list[dict[str, Any]]) -> None:
    """Upload video attachments to the Files API, annotating file dicts in place.

    Adds "gemini_file_uri" on success or "gemini_upload_error" on failure.
    Never raises — a failed video upload must not fail the whole chat request.
    """
    for idx, file in enumerate(files):
        mime_type = file.get("type", "")
        if not mime_type.startswith("video/"):
            continue
        try:
            data = base64.b64decode(file.get("data", ""))
            file["gemini_file_uri"] = ensure_gemini_file_uri(message_id, idx, data, mime_type)
        except Exception as e:
            # Broad catch is deliberate: any failure here (upload, DB cache,
            # client construction) must degrade to a text notice for the LLM,
            # never fail the whole chat request.
            logger.error(
                "Failed to prepare video for Gemini",
                extra={"message_id": message_id, "file_index": idx, "error": str(e)},
                exc_info=not isinstance(e, (GeminiFileError, binascii.Error)),
            )
            file["gemini_upload_error"] = str(e)


def delete_cached_file_uri(message_id: str, file_index: int) -> None:
    """Drop the cached Files API URI (used by the retention sweep)."""
    db.kv_delete(SYSTEM_KV_USER_ID, GEMINI_FILES_NAMESPACE, _cache_key(message_id, file_index))
