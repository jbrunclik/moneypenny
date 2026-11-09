"""Proposals: one record for anything awaiting the user's yes.

One approval mechanism, step 1 (docs/superpowers/specs/2026-11-09-one-approval-
mechanism-design.md). A proposal carries 1-4 options, each with the exact
payload choosing it applies, and is shown as a card under its reply. Changes
bump the conversation in the sync change log (as messages do, 0061), so
another device sees a card resolved; deleting its reply expires an open one
(timestamps in the stored fixed-width form). The chat setups' old kv previews
(the pending gate) are cleared: they lived for one message only.
"""

from yoyo import step

__depends__ = {"0085_announcement_post_messages"}

_CONV_USER = "(SELECT user_id FROM conversations WHERE id = NEW.conversation_id)"
_BUMP = f"""
            UPDATE sync_counter SET value = value + 1 WHERE id = 1;
            INSERT INTO conversation_changes (conversation_id, user_id, seq)
            SELECT NEW.conversation_id, {_CONV_USER}, (SELECT value FROM sync_counter WHERE id = 1)
            WHERE {_CONV_USER} IS NOT NULL
            ON CONFLICT(conversation_id) DO UPDATE SET seq = excluded.seq;"""

steps = [
    step(
        """CREATE TABLE proposals (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            conversation_id TEXT NOT NULL,
            message_id TEXT,
            request_id TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,
            summary TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '{}',
            options TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending',
            chosen INTEGER,
            result TEXT,
            resolved_by TEXT,
            reported INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            resolved_at TEXT
        )""",
        "DROP TABLE proposals",
    ),
    step(
        "CREATE INDEX idx_proposals_conversation_state ON proposals(conversation_id, state)",
        "DROP INDEX IF EXISTS idx_proposals_conversation_state",
    ),
    step(
        "CREATE INDEX idx_proposals_message ON proposals(message_id)",
        "DROP INDEX IF EXISTS idx_proposals_message",
    ),
    step(
        f"CREATE TRIGGER sync_change_proposal_insert AFTER INSERT ON proposals BEGIN{_BUMP}\n        END",
        "DROP TRIGGER IF EXISTS sync_change_proposal_insert",
    ),
    step(
        f"CREATE TRIGGER sync_change_proposal_update AFTER UPDATE ON proposals BEGIN{_BUMP}\n        END",
        "DROP TRIGGER IF EXISTS sync_change_proposal_update",
    ),
    # A deleted reply (regenerate, truncate, delete) takes its open cards
    # with it: a proposal is never approvable from a message that is gone
    step(
        """CREATE TRIGGER proposals_expire_with_their_reply AFTER DELETE ON messages BEGIN
            UPDATE proposals SET state = 'expired', resolved_by = 'system',
                resolved_at = strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000+00:00'
            WHERE message_id = OLD.id AND state = 'pending';
        END""",
        "DROP TRIGGER IF EXISTS proposals_expire_with_their_reply",
    ),
    step(
        """DELETE FROM kv_store
           WHERE namespace IN ('schedule_pending', 'standing_create_pending', 'standing_pending')""",
        "SELECT 1",
    ),
]
