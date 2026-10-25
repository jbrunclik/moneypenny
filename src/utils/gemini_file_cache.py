"""kv_store layout of the cached Gemini Files API URIs.

src/agent/gemini_files.py reads and writes the cache; the retention sweep
(src/utils/file_retention.py) deletes entries for expired videos. The layout
lives here, below both, so the sweep needs nothing from the agent layer.
"""

from src.db import models

GEMINI_FILES_NAMESPACE = "gemini_files"
SYSTEM_KV_USER_ID = "_system"


def cache_key(message_id: str, file_index: int) -> str:
    """kv_store key of one attachment's cached URI."""
    return f"{message_id}:{file_index}"


def delete_cached_file_uri(message_id: str, file_index: int) -> None:
    """Drop the cached Files API URI (used by the retention sweep)."""
    models.db.kv_delete(
        SYSTEM_KV_USER_ID, GEMINI_FILES_NAMESPACE, cache_key(message_id, file_index)
    )
