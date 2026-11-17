"""The search index follows a message's text when it changes.

The index had insert and delete triggers on messages but none for updates,
so a reply saved as a placeholder and filled in later kept its old (often
empty) indexed text - 16 of 320 assistant replies in a local copy (Nov 17
2026) - and an edited message would keep its old text searchable. The
trigger copies the new text and drops the message's embedding (computed
from the old text). The backfill fixes the rows already stale.
"""

from yoyo import step

__depends__ = {"0100_side_costs_service_tier"}

steps = [
    step(
        """CREATE TRIGGER fts_update_message AFTER UPDATE OF content ON messages
           WHEN NEW.content IS NOT OLD.content
           BEGIN
               UPDATE search_index SET content = NEW.content WHERE rowid IN (
                   SELECT fts_rowid FROM search_index_keys WHERE message_id = NEW.id);
               DELETE FROM embeddings WHERE kind = 'message' AND ref_id = NEW.id;
           END""",
        "DROP TRIGGER fts_update_message",
    ),
    step(
        """UPDATE search_index
           SET content = (
               SELECT m.content FROM search_index_keys k JOIN messages m ON m.id = k.message_id
               WHERE k.fts_rowid = search_index.rowid)
           WHERE rowid IN (
               SELECT k.fts_rowid FROM search_index_keys k
               JOIN messages m ON m.id = k.message_id
               JOIN search_index s ON s.rowid = k.fts_rowid
               WHERE s.content IS NOT m.content)""",
        # The stale text is gone; nothing to restore
        "SELECT 1",
    ),
]
