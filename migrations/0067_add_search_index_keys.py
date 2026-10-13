"""Look up search index rows by key instead of scanning the index.

search_index (FTS5) keeps conversation_id / message_id as UNINDEXED columns,
so every trigger that deleted by id scanned the whole index - once per
deleted message. Bulk deletes went quadratic (Oct 13 2026: emptying a
1000-chat trash took minutes at ~16k index rows).

search_index_keys maps each index row (by FTS rowid) to its conversation and
message, with ordinary b-tree indexes; the triggers now find rows through it.
Its rowid is an INTEGER PRIMARY KEY, so VACUUM keeps it stable (the implicit
rowid of messages would not be). The search query itself is unchanged.
"""

from typing import Any

from yoyo import step

__depends__ = {"0066_add_conversation_trashed_updated_at"}

_NEW_TRIGGERS = {
    "fts_insert_conversation": """CREATE TRIGGER fts_insert_conversation AFTER INSERT ON conversations
        WHEN (NEW.is_planning = 0 OR NEW.is_planning IS NULL)
        AND (NEW.is_agent = 0 OR NEW.is_agent IS NULL)
        AND (NEW.archived = 0 OR NEW.archived IS NULL)
        AND (NEW.is_sports = 0 OR NEW.is_sports IS NULL)
        AND (NEW.is_language = 0 OR NEW.is_language IS NULL)
        BEGIN
            INSERT INTO search_index_keys(conversation_id, message_id) VALUES (NEW.id, NULL);
            INSERT INTO search_index(rowid, user_id, conversation_id, message_id, type, title, content)
            VALUES (last_insert_rowid(), NEW.user_id, NEW.id, NULL, 'conversation', NEW.title, '');
        END""",
    "fts_update_conversation": """CREATE TRIGGER fts_update_conversation AFTER UPDATE ON conversations
        WHEN OLD.title != NEW.title
        AND (NEW.is_planning = 0 OR NEW.is_planning IS NULL)
        AND (NEW.is_agent = 0 OR NEW.is_agent IS NULL)
        AND (NEW.archived = 0 OR NEW.archived IS NULL)
        AND (NEW.is_sports = 0 OR NEW.is_sports IS NULL)
        AND (NEW.is_language = 0 OR NEW.is_language IS NULL)
        BEGIN
            DELETE FROM search_index WHERE rowid IN (
                SELECT fts_rowid FROM search_index_keys
                WHERE conversation_id = OLD.id AND message_id IS NULL);
            DELETE FROM search_index_keys WHERE conversation_id = OLD.id AND message_id IS NULL;
            INSERT INTO search_index_keys(conversation_id, message_id) VALUES (NEW.id, NULL);
            INSERT INTO search_index(rowid, user_id, conversation_id, message_id, type, title, content)
            VALUES (last_insert_rowid(), NEW.user_id, NEW.id, NULL, 'conversation', NEW.title, '');
        END""",
    "fts_delete_conversation": """CREATE TRIGGER fts_delete_conversation AFTER DELETE ON conversations
        BEGIN
            DELETE FROM search_index WHERE rowid IN (
                SELECT fts_rowid FROM search_index_keys WHERE conversation_id = OLD.id);
            DELETE FROM search_index_keys WHERE conversation_id = OLD.id;
        END""",
    "fts_insert_message": """CREATE TRIGGER fts_insert_message AFTER INSERT ON messages
        WHEN EXISTS (
            SELECT 1 FROM conversations c
            WHERE c.id = NEW.conversation_id
            AND (c.is_planning = 0 OR c.is_planning IS NULL)
            AND (c.is_agent = 0 OR c.is_agent IS NULL)
            AND (c.archived = 0 OR c.archived IS NULL)
            AND (c.is_sports = 0 OR c.is_sports IS NULL)
            AND (c.is_language = 0 OR c.is_language IS NULL))
        BEGIN
            INSERT INTO search_index_keys(conversation_id, message_id)
            VALUES (NEW.conversation_id, NEW.id);
            INSERT INTO search_index(rowid, user_id, conversation_id, message_id, type, title, content)
            SELECT last_insert_rowid(), c.user_id, NEW.conversation_id, NEW.id, 'message', '', NEW.content
            FROM conversations c WHERE c.id = NEW.conversation_id;
        END""",
    "fts_delete_message": """CREATE TRIGGER fts_delete_message AFTER DELETE ON messages
        BEGIN
            DELETE FROM search_index WHERE rowid IN (
                SELECT fts_rowid FROM search_index_keys WHERE message_id = OLD.id);
            DELETE FROM search_index_keys WHERE message_id = OLD.id;
        END""",
}

# The triggers as they were (0024..0058), for the rollback
_OLD_TRIGGERS = {
    "fts_delete_conversation": """CREATE TRIGGER fts_delete_conversation AFTER DELETE ON conversations
        BEGIN
            DELETE FROM search_index WHERE conversation_id = OLD.id;
        END""",
    "fts_delete_message": """CREATE TRIGGER fts_delete_message AFTER DELETE ON messages
        BEGIN
            DELETE FROM search_index WHERE message_id = OLD.id;
        END""",
    "fts_insert_conversation": """CREATE TRIGGER fts_insert_conversation AFTER INSERT ON conversations
        WHEN (NEW.is_planning = 0 OR NEW.is_planning IS NULL)
        AND (NEW.is_agent = 0 OR NEW.is_agent IS NULL)
        AND (NEW.archived = 0 OR NEW.archived IS NULL)
        AND (NEW.is_sports = 0 OR NEW.is_sports IS NULL)
        AND (NEW.is_language = 0 OR NEW.is_language IS NULL)
        BEGIN
            INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
            VALUES (NEW.user_id, NEW.id, NULL, 'conversation', NEW.title, '');
        END""",
    "fts_insert_message": """CREATE TRIGGER fts_insert_message AFTER INSERT ON messages
        BEGIN
            INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
            SELECT c.user_id, NEW.conversation_id, NEW.id, 'message', '', NEW.content
            FROM conversations c
            WHERE c.id = NEW.conversation_id
            AND (c.is_planning = 0 OR c.is_planning IS NULL)
            AND (c.is_agent = 0 OR c.is_agent IS NULL)
            AND (c.archived = 0 OR c.archived IS NULL)
            AND (c.is_sports = 0 OR c.is_sports IS NULL)
            AND (c.is_language = 0 OR c.is_language IS NULL);
        END""",
    "fts_update_conversation": """CREATE TRIGGER fts_update_conversation AFTER UPDATE ON conversations
        WHEN OLD.title != NEW.title
        AND (NEW.is_planning = 0 OR NEW.is_planning IS NULL)
        AND (NEW.is_agent = 0 OR NEW.is_agent IS NULL)
        AND (NEW.archived = 0 OR NEW.archived IS NULL)
        AND (NEW.is_sports = 0 OR NEW.is_sports IS NULL)
        AND (NEW.is_language = 0 OR NEW.is_language IS NULL)
        BEGIN
            DELETE FROM search_index WHERE conversation_id = OLD.id AND type = 'conversation';
            INSERT INTO search_index(user_id, conversation_id, message_id, type, title, content)
            VALUES (NEW.user_id, NEW.id, NULL, 'conversation', NEW.title, '');
        END""",
}


def add_keys(conn: Any) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """CREATE TABLE search_index_keys (
               fts_rowid INTEGER PRIMARY KEY,
               conversation_id TEXT NOT NULL,
               message_id TEXT)"""
    )
    # Backfill with the index's own rowids. Some databases indexed a message
    # (or a title) more than once - search then returned it twice - so keep
    # the first row of each and drop the rest from the index.
    cursor.execute(
        """INSERT INTO search_index_keys(fts_rowid, conversation_id, message_id)
           SELECT MIN(rowid), conversation_id, message_id FROM search_index
           WHERE message_id IS NOT NULL GROUP BY message_id
           UNION ALL
           SELECT MIN(rowid), conversation_id, NULL FROM search_index
           WHERE message_id IS NULL GROUP BY conversation_id"""
    )
    cursor.execute(
        "DELETE FROM search_index WHERE rowid NOT IN (SELECT fts_rowid FROM search_index_keys)"
    )
    cursor.execute(
        "CREATE INDEX idx_search_index_keys_conversation ON search_index_keys(conversation_id)"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX idx_search_index_keys_message ON search_index_keys(message_id)"
    )
    for name, sql in _NEW_TRIGGERS.items():
        cursor.execute(f"DROP TRIGGER IF EXISTS {name}")
        cursor.execute(sql)


def drop_keys(conn: Any) -> None:
    cursor = conn.cursor()
    for name, sql in _OLD_TRIGGERS.items():
        cursor.execute(f"DROP TRIGGER IF EXISTS {name}")
        cursor.execute(sql)
    cursor.execute("DROP TABLE IF EXISTS search_index_keys")


steps = [step(add_keys, drop_keys)]
