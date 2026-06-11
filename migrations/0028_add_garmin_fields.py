"""
Add Garmin Connect fields to users table.

This migration adds columns for storing the user's serialized garth session
tokens and connection timestamp for the Garmin Connect integration.
"""

from yoyo import step

__depends__ = {"0027_upgrade_pro_model"}

steps = [
    step(
        "ALTER TABLE users ADD COLUMN garmin_token TEXT",
        "ALTER TABLE users DROP COLUMN garmin_token",
    ),
    step(
        "ALTER TABLE users ADD COLUMN garmin_connected_at TEXT",
        "ALTER TABLE users DROP COLUMN garmin_connected_at",
    ),
]
