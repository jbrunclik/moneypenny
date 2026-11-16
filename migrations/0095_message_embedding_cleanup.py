"""A message's embedding goes with the message. Nothing deleted them, so by
Nov 16 2026 26.1k of 44.0k message embeddings in production belonged to
deleted messages (one user: 18.4k of 19.8k), all scored on every past-chat
search. The trigger covers every delete path (a message, a truncation, a
conversation, the trash purge); trashed conversations keep theirs until the
purge, so a restored chat is still found by meaning
(docs/superpowers/specs/2026-11-16-past-chat-search-design.md)."""

from yoyo import step

__depends__ = {"0094_memory_summary"}

PURGE_ORPHANS_SQL = (
    "DELETE FROM embeddings WHERE kind = 'message' AND ref_id NOT IN (SELECT id FROM messages)"
)

# irreversible: the purged embeddings belonged to messages that no longer exist
steps = [
    step(PURGE_ORPHANS_SQL),
    step(
        """CREATE TRIGGER messages_embedding_delete
           AFTER DELETE ON messages
           BEGIN
               DELETE FROM embeddings WHERE kind = 'message' AND ref_id = OLD.id;
           END""",
        "DROP TRIGGER messages_embedding_delete",
    ),
]
