"""
Add app_settings table for storing application-wide settings.

This table stores key-value pairs for settings that need to be updated
at runtime without restarting the application, such as currency rates.
"""

from yoyo import step

steps = [
    step(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        "DROP TABLE IF EXISTS app_settings",
    ),
]
