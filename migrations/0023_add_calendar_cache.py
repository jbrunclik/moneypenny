"""Add calendar cache table for available calendars.

This migration creates a cache table to store the list of available calendars
fetched from Google Calendar API. Cache has 1-hour TTL to reduce API calls.
"""

from yoyo import step

__depends__ = {"0022_add_calendar_selection"}

steps = [
    step(
        """
        CREATE TABLE IF NOT EXISTS calendar_cache (
            user_id TEXT PRIMARY KEY,
            calendars_data TEXT NOT NULL,
            cached_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
        """,
        "DROP TABLE IF EXISTS calendar_cache",
    ),
    step(
        "CREATE INDEX IF NOT EXISTS idx_calendar_cache_expires ON calendar_cache(expires_at)",
        "DROP INDEX IF EXISTS idx_calendar_cache_expires",
    ),
]
