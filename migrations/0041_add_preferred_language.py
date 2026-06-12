"""
Add users.preferred_language for the primary-language setting.

NULL = auto (match the language the user writes in). When set, the
dynamic user context instructs the model to respond in this language
even when the visible user message is a system-generated English
trigger ("Start my training session", "[Triggered: scheduled]", ...).
"""

from yoyo import step

__depends__ = {"0040_heal_briefing_tool_permissions"}

steps = [
    step(
        "ALTER TABLE users ADD COLUMN preferred_language TEXT",
        "ALTER TABLE users DROP COLUMN preferred_language",
    ),
]
