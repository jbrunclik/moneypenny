"""
Add context_cache table for sharing Gemini context caches across workers.

The ContextCacheManager previously tracked created caches only in process
memory, so each gunicorn worker created its own Gemini cached-content entry
for identical content - multiplying cache storage billing by the worker
count and starting cold after every reload. This table lets workers share
one cache per (profile, model) keyed entry.
"""

from yoyo import step

__depends__ = {"0033_upgrade_fast_model"}

steps = [
    step(
        """
        CREATE TABLE context_cache (
            cache_key TEXT PRIMARY KEY,
            cache_name TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )
        """,
        "DROP TABLE IF EXISTS context_cache",
    ),
]
