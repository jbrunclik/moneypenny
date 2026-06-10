"""
Add stream_journal table for resumable chat streams.

The chat-stream producer journals every SSE event (token/thinking/tool
activity) per assistant-message-id with a monotonic sequence number.
A client that loses its connection (mobile background, wifi->cellular
switch) reconnects to the resume endpoint with the last seq it rendered;
the server replays the journal from that offset and continues live -
generation itself already survives disconnects (producer thread +
cleanup save). Rows are short-lived and swept by age.
"""

from yoyo import step

__depends__ = {"0034_add_context_cache_table"}

steps = [
    step(
        """
        CREATE TABLE stream_journal (
            message_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            event TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (message_id, seq)
        )
        """,
        "DROP TABLE IF EXISTS stream_journal",
    ),
    step(
        "CREATE INDEX idx_stream_journal_created ON stream_journal(created_at)",
        "DROP INDEX IF EXISTS idx_stream_journal_created",
    ),
]
