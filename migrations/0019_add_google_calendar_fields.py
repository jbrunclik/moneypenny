"""Add Google Calendar integration fields to users table."""

from yoyo import step

steps = [
    step(
        "ALTER TABLE users ADD COLUMN google_calendar_access_token TEXT",
        "ALTER TABLE users DROP COLUMN google_calendar_access_token",
    ),
    step(
        "ALTER TABLE users ADD COLUMN google_calendar_refresh_token TEXT",
        "ALTER TABLE users DROP COLUMN google_calendar_refresh_token",
    ),
    step(
        "ALTER TABLE users ADD COLUMN google_calendar_token_expires_at DATETIME",
        "ALTER TABLE users DROP COLUMN google_calendar_token_expires_at",
    ),
    step(
        "ALTER TABLE users ADD COLUMN google_calendar_connected_at DATETIME",
        "ALTER TABLE users DROP COLUMN google_calendar_connected_at",
    ),
    step(
        "ALTER TABLE users ADD COLUMN google_calendar_email TEXT",
        "ALTER TABLE users DROP COLUMN google_calendar_email",
    ),
]
