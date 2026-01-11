"""Add calendar selection support for Google Calendar.

This migration adds a column to store which calendars the user wants
to include in the planner context. Defaults to primary calendar only
for backward compatibility.
"""

from yoyo import step

__depends__ = {"0021_add_weather_cache"}

steps = [
    step(
        "ALTER TABLE users ADD COLUMN google_calendar_selected_ids TEXT DEFAULT '[\"primary\"]'",
        "ALTER TABLE users DROP COLUMN google_calendar_selected_ids",
    ),
]
