"""Drop the context_cache table: it held the shared Gemini explicit-cache names,
and Gemini 4 has no explicit cache (the code path was removed Nov 2026)."""

from yoyo import step

__depends__ = {"0097_client_boot_timings_hidden"}

steps = [
    step(
        "DROP TABLE IF EXISTS context_cache",
        """
        CREATE TABLE context_cache (
            cache_key TEXT PRIMARY KEY,
            cache_name TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )
        """,
    ),
]
