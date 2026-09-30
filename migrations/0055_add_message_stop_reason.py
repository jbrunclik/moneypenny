"""Add stop_reason to messages.

Why an assistant reply ended early: "user" when the user pressed Stop and
the server ended the turn (partial reply kept, Continue offered). NULL for
normal replies. The tool-round cap keeps being derived from message_costs.
"""

from yoyo import step

__depends__ = {"0054_add_message_tool_outputs"}

steps = [
    step(
        "ALTER TABLE messages ADD COLUMN stop_reason TEXT",
        "ALTER TABLE messages DROP COLUMN stop_reason",
    ),
]
