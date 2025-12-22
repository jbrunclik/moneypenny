"""
Add details column to messages table.

Stores thinking and tool call/result events for assistant messages.
- details: JSON array of detail events (nullable)

Each detail event has a 'type' field:
- thinking: {"type": "thinking", "content": "..."}
- tool_call: {"type": "tool_call", "id": "...", "name": "...", "args": {...}}
- tool_result: {"type": "tool_result", "tool_call_id": "...", "content": "..."}
"""

from yoyo import step

steps = [
    step(
        "ALTER TABLE messages ADD COLUMN details TEXT",
        # SQLite doesn't support DROP COLUMN easily, but for rollback we just ignore it
        ""
    ),
]
