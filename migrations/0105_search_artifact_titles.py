"""Chat search finds an artifact's title.

Artifact titles were not indexed, so a chat that built "Wallbox wiring
diagram" was found only if its text said so. Each artifact now has a
search_index row (type 'artifact', its title) pointing at the reply that first
built it; triggers keep the row with the artifact (created, retitled, deleted -
its delete follows the reply's and the chat's), and the backfill indexes the
artifacts there are. The rows are keyed by search_index_keys.artifact_id: the
chat-title trigger re-keys rows with no message_id, so it now leaves artifact
rows alone.
"""

from yoyo import step

__depends__ = {"0104_projects"}

# A conversation search indexes (as for its messages)
_INDEXED = """EXISTS (
            SELECT 1 FROM conversations c
            WHERE c.id = {conv}
            AND (c.is_planning = 0 OR c.is_planning IS NULL)
            AND (c.is_agent = 0 OR c.is_agent IS NULL)
            AND (c.archived = 0 OR c.archived IS NULL)
            AND (c.is_sports = 0 OR c.is_sports IS NULL)
            AND (c.is_language = 0 OR c.is_language IS NULL))"""

_TITLE_TRIGGER = """CREATE TRIGGER fts_update_conversation AFTER UPDATE ON conversations
        WHEN OLD.title != NEW.title
        AND (NEW.is_planning = 0 OR NEW.is_planning IS NULL)
        AND (NEW.is_agent = 0 OR NEW.is_agent IS NULL)
        AND (NEW.archived = 0 OR NEW.archived IS NULL)
        AND (NEW.is_sports = 0 OR NEW.is_sports IS NULL)
        AND (NEW.is_language = 0 OR NEW.is_language IS NULL)
        BEGIN
            DELETE FROM search_index WHERE rowid IN (
                SELECT fts_rowid FROM search_index_keys
                WHERE conversation_id = OLD.id AND message_id IS NULL{keep});
            DELETE FROM search_index_keys
                WHERE conversation_id = OLD.id AND message_id IS NULL{keep};
            INSERT INTO search_index_keys(conversation_id, message_id) VALUES (NEW.id, NULL);
            INSERT INTO search_index(rowid, user_id, conversation_id, message_id, type, title, content)
            VALUES (last_insert_rowid(), NEW.user_id, NEW.id, NULL, 'conversation', NEW.title, '');
        END"""

steps = [
    step(
        "ALTER TABLE search_index_keys ADD COLUMN artifact_id TEXT",
        "ALTER TABLE search_index_keys DROP COLUMN artifact_id",
    ),
    step(
        "CREATE INDEX idx_search_index_keys_artifact ON search_index_keys(artifact_id)",
        "DROP INDEX IF EXISTS idx_search_index_keys_artifact",
    ),
    step(
        "DROP TRIGGER fts_update_conversation",
        _TITLE_TRIGGER.format(keep=""),
    ),
    step(
        _TITLE_TRIGGER.format(keep=" AND artifact_id IS NULL"),
        "DROP TRIGGER fts_update_conversation",
    ),
    step(
        f"""CREATE TRIGGER fts_insert_artifact AFTER INSERT ON artifacts
            WHEN {_INDEXED.format(conv="NEW.conversation_id")}
            BEGIN
                INSERT INTO search_index_keys(conversation_id, message_id, artifact_id)
                VALUES (NEW.conversation_id, NULL, NEW.id);
                INSERT INTO search_index(rowid, user_id, conversation_id, message_id, type,
                                         title, content)
                VALUES (last_insert_rowid(), NEW.user_id, NEW.conversation_id, NULL,
                        'artifact', NEW.title, '');
            END""",
        "DROP TRIGGER fts_insert_artifact",
    ),
    step(
        """CREATE TRIGGER fts_update_artifact AFTER UPDATE OF title ON artifacts
           WHEN NEW.title IS NOT OLD.title
           BEGIN
               UPDATE search_index SET title = NEW.title WHERE rowid IN (
                   SELECT fts_rowid FROM search_index_keys WHERE artifact_id = NEW.id);
           END""",
        "DROP TRIGGER fts_update_artifact",
    ),
    step(
        """CREATE TRIGGER fts_delete_artifact AFTER DELETE ON artifacts
           BEGIN
               DELETE FROM search_index WHERE rowid IN (
                   SELECT fts_rowid FROM search_index_keys WHERE artifact_id = OLD.id);
               DELETE FROM search_index_keys WHERE artifact_id = OLD.id;
           END""",
        "DROP TRIGGER fts_delete_artifact",
    ),
    # The reply that built version 1 is linked after the turn saves it; a hit
    # opens that reply. Kept out of search_index_keys.message_id, which the
    # message triggers use to rewrite or drop a message's own row.
    step(
        """CREATE TRIGGER fts_link_artifact AFTER UPDATE OF created_by_message_id
               ON artifact_versions
           WHEN NEW.version = 1
           BEGIN
               UPDATE search_index SET message_id = NEW.created_by_message_id WHERE rowid IN (
                   SELECT fts_rowid FROM search_index_keys WHERE artifact_id = NEW.artifact_id);
           END""",
        "DROP TRIGGER fts_link_artifact",
    ),
    step(
        f"""INSERT INTO search_index_keys(conversation_id, message_id, artifact_id)
            SELECT a.conversation_id, NULL, a.id FROM artifacts a
            WHERE {_INDEXED.format(conv="a.conversation_id")}""",
        "DELETE FROM search_index_keys WHERE artifact_id IS NOT NULL",
    ),
    step(
        """INSERT INTO search_index(rowid, user_id, conversation_id, message_id, type, title,
                                   content)
           SELECT k.fts_rowid, a.user_id, a.conversation_id,
                  (SELECT v.created_by_message_id FROM artifact_versions v
                   WHERE v.artifact_id = a.id AND v.version = 1),
                  'artifact', a.title, ''
           FROM search_index_keys k JOIN artifacts a ON a.id = k.artifact_id""",
        "DELETE FROM search_index WHERE type = 'artifact'",
    ),
]
