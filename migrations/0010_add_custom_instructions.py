"""
Add custom_instructions column to users table.

This migration adds a column for storing user-defined custom instructions
that customize LLM behavior (e.g., "respond in Czech", "be concise").
"""

from yoyo import step

steps = [
    step(
        "ALTER TABLE users ADD COLUMN custom_instructions TEXT",
        "ALTER TABLE users DROP COLUMN custom_instructions",
    ),
]
