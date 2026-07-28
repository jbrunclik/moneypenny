"""
Persist anonymous mode per conversation.

Anonymous mode (no memory read/write, no integrations) was client-side state
only: a Map in the Zustand store, lost on refresh. A conversation the user had
deliberately marked private silently became memory-enabled after a page reload,
which is the opposite of what the toggle promises.

Storing it on the conversation makes the setting survive reloads and lets the
server decide, rather than trusting a per-request flag from the client.
"""

from yoyo import step

__depends__ = {"0046_add_memory_provenance_and_soft_delete"}

steps = [
    step(
        "ALTER TABLE conversations ADD COLUMN anonymous_mode INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE conversations DROP COLUMN anonymous_mode",
    ),
]
