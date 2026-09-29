"""Add tool_outputs to messages.

JSON array of compact per-call digests ({tool, args, result}) for an
assistant turn's non-web tool calls (Garmin, Todoist, kv_store, code...).
Rendered into the message's MSG_CONTEXT in later turns so follow-up questions
about an earlier tool result can be answered without re-calling the tool.
See src/agent/tool_outputs.py.
"""

from yoyo import step

__depends__ = {"0053_upgrade_fast_model"}

steps = [
    step(
        "ALTER TABLE messages ADD COLUMN tool_outputs TEXT",
        "ALTER TABLE messages DROP COLUMN tool_outputs",
    ),
]
