"""
Drop the agent_states table.

The agent_states table was used to persist LangGraph agent state between batch mode requests.
This is no longer needed as both batch and streaming modes now reconstruct conversation
history from the messages table, which is simpler and more consistent.
"""

from yoyo import step

steps = [
    step(
        # Up migration - drop the table
        "DROP TABLE IF EXISTS agent_states",
        # Down migration - recreate the table (for rollback)
        """
        CREATE TABLE IF NOT EXISTS agent_states (
            conversation_id TEXT PRIMARY KEY,
            state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
        """
    ),
]
