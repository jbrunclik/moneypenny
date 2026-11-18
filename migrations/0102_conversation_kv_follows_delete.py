"""A chat's kv state goes with the chat. Its compaction summary, memory-review
cursor ("<conv>" and "<conv>:turns"), stop/finish/steering flags and lost-turn
note are keyed by conversation id, and no delete path removed them: by Nov 18
2026, 187 of 262 compaction summaries in production (1.07 MB) belonged to
deleted chats. The trigger covers every hard delete (a chat, the trash purge,
a standing chat, a program); trashed chats keep theirs until the purge, so a
restored chat resumes where it was. The backfill drops the orphans already
there, and the media sweep's last-run stamp it renamed to file_cleanup.
"""

from yoyo import step

__depends__ = {"0101_search_index_follows_message_edits"}

# Owners: agent/conversation_compaction, api/helpers/memory_review_trigger,
# agent/cancellation (three), agent/interjection, api/helpers/lost_actions.
# A test checks the trigger names each owner's constant
NAMESPACES_SQL = (
    "'conv_compaction', 'memory_review', 'cancel', 'cancel_pending',"
    " 'deep_research_finish', 'interject', 'lost_actions'"
)

PURGE_ORPHANS_SQL = f"""
    DELETE FROM kv_store WHERE namespace IN ({NAMESPACES_SQL})
    AND (CASE instr(key, ':') WHEN 0 THEN key ELSE substr(key, 1, instr(key, ':') - 1) END)
        NOT IN (SELECT id FROM conversations)"""

# irreversible: the purged rows belonged to chats that no longer exist
steps = [
    step(
        f"""CREATE TRIGGER conversations_kv_delete
           AFTER DELETE ON conversations
           BEGIN
               DELETE FROM kv_store WHERE user_id = OLD.user_id
               AND namespace IN ({NAMESPACES_SQL})
               AND (key = OLD.id OR substr(key, 1, length(OLD.id) + 1) = OLD.id || ':');
           END""",
        "DROP TRIGGER conversations_kv_delete",
    ),
    step(PURGE_ORPHANS_SQL),
    step("DELETE FROM kv_store WHERE namespace = 'media_cleanup' AND key = 'last_run'"),
]
