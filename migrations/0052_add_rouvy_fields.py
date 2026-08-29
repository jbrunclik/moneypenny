"""Add Rouvy integration fields to users table.

Stores the user's Rouvy email + password (Fernet-encrypted) and the serialized
session-cookie blob so the session can be auto-refreshed via headless login.
"""

from yoyo import step

__depends__ = {"0051_pin_conversations"}

steps = [
    step(
        "ALTER TABLE users ADD COLUMN rouvy_email TEXT",
        "ALTER TABLE users DROP COLUMN rouvy_email",
    ),
    step(
        "ALTER TABLE users ADD COLUMN rouvy_password TEXT",
        "ALTER TABLE users DROP COLUMN rouvy_password",
    ),
    step(
        "ALTER TABLE users ADD COLUMN rouvy_session TEXT",
        "ALTER TABLE users DROP COLUMN rouvy_session",
    ),
    step(
        "ALTER TABLE users ADD COLUMN rouvy_connected_at TEXT",
        "ALTER TABLE users DROP COLUMN rouvy_connected_at",
    ),
]
