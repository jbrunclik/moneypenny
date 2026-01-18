"""
Add WhatsApp phone number field to users table.

This migration adds a column for storing the user's WhatsApp phone number
for receiving notifications from autonomous agents.
"""

from yoyo import step

steps = [
    step(
        "ALTER TABLE users ADD COLUMN whatsapp_phone TEXT",
        "ALTER TABLE users DROP COLUMN whatsapp_phone",
    ),
]
