"""
Add provenance, protection and soft-delete to user_memories.

protected            = never auto-delete this memory. The "never delete family
                       names / identity facts" rule was prompt-only, so a single
                       bad LLM turn or defrag run could drop it. Now it is an
                       invariant enforced in the delete paths.
source_conversation_id = which conversation the memory was learned in, so the
                       user can answer "why do you know this?" and so defrag has
                       a provenance signal instead of guessing from content.
deleted_at           = soft delete. Deletes are the only irreversible memory
                       operation and they can be triggered by the LLM (including
                       via prompt-injected web content) or by a bad defrag run.
                       Rows linger for MEMORY_SOFT_DELETE_RETENTION_DAYS and are
                       purged by the nightly job.

The partial index keeps the common "live memories for this user" read fast
without the deleted rows.
"""

from yoyo import step

__depends__ = {"0045_upgrade_fast_model"}

steps = [
    step(
        "ALTER TABLE user_memories ADD COLUMN protected INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE user_memories DROP COLUMN protected",
    ),
    step(
        "ALTER TABLE user_memories ADD COLUMN source_conversation_id TEXT",
        "ALTER TABLE user_memories DROP COLUMN source_conversation_id",
    ),
    step(
        "ALTER TABLE user_memories ADD COLUMN deleted_at TEXT",
        "ALTER TABLE user_memories DROP COLUMN deleted_at",
    ),
    step(
        """
        CREATE INDEX IF NOT EXISTS idx_user_memories_live
        ON user_memories(user_id, updated_at DESC)
        WHERE deleted_at IS NULL
        """,
        "DROP INDEX IF EXISTS idx_user_memories_live",
    ),
]
