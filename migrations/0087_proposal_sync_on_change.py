"""Proposals bump the sync change log only when what a device shows changes.

0086's update trigger fired on every write, so marking an outcome reported
(the agent heard it) cost every device a refetch. The card shows state,
chosen, result and its reply - only those columns bump now.
"""

from yoyo import step

__depends__ = {"0086_proposals"}

_CONV_USER = "(SELECT user_id FROM conversations WHERE id = NEW.conversation_id)"
_BUMP = f"""
            UPDATE sync_counter SET value = value + 1 WHERE id = 1;
            INSERT INTO conversation_changes (conversation_id, user_id, seq)
            SELECT NEW.conversation_id, {_CONV_USER}, (SELECT value FROM sync_counter WHERE id = 1)
            WHERE {_CONV_USER} IS NOT NULL
            ON CONFLICT(conversation_id) DO UPDATE SET seq = excluded.seq;"""
_ANY = "AFTER UPDATE ON proposals"
_SHOWN = "AFTER UPDATE OF state, chosen, result, message_id ON proposals"

steps = [
    step(
        "DROP TRIGGER IF EXISTS sync_change_proposal_update",
        f"CREATE TRIGGER sync_change_proposal_update {_ANY} BEGIN{_BUMP}\n        END",
    ),
    step(
        f"CREATE TRIGGER sync_change_proposal_update {_SHOWN} BEGIN{_BUMP}\n        END",
        "DROP TRIGGER IF EXISTS sync_change_proposal_update",
    ),
]
