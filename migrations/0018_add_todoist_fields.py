"""
Add Todoist integration fields to users table.

This migration adds columns for storing Todoist OAuth access tokens
and connection timestamp for the task management integration.
"""

from yoyo import step

steps = [
    step(
        "ALTER TABLE users ADD COLUMN todoist_access_token TEXT",
        "ALTER TABLE users DROP COLUMN todoist_access_token",
    ),
    step(
        "ALTER TABLE users ADD COLUMN todoist_connected_at DATETIME",
        "ALTER TABLE users DROP COLUMN todoist_connected_at",
    ),
]
