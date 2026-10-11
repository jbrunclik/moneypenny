"""Add artifacts: agent-made HTML/JS shown inline in a sandboxed frame.

Spec: docs/superpowers/specs/2026-10-11-inline-artifacts-design.md. Foreign keys
are not enforced and messages are deleted from many places, so cleanup is by
trigger: a message's versions go with it, an artifact goes with its last version
and with its conversation.
"""

from yoyo import step

__depends__ = {"0064_purge_stale_interjections"}

steps = [
    step(
        """CREATE TABLE artifacts (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            latest_version INTEGER NOT NULL DEFAULT 1,
            state TEXT,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL
        )""",
        "DROP TABLE artifacts",
    ),
    step(
        "CREATE INDEX idx_artifacts_conversation ON artifacts(conversation_id)",
        "DROP INDEX IF EXISTS idx_artifacts_conversation",
    ),
    step(
        """CREATE TABLE artifact_versions (
            artifact_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            html TEXT NOT NULL,
            created_by_message_id TEXT,
            created_at TIMESTAMP NOT NULL,
            PRIMARY KEY (artifact_id, version)
        )""",
        "DROP TABLE artifact_versions",
    ),
    step(
        "CREATE INDEX idx_artifact_versions_message ON artifact_versions(created_by_message_id)",
        "DROP INDEX IF EXISTS idx_artifact_versions_message",
    ),
    step(
        "ALTER TABLE messages ADD COLUMN artifacts TEXT",
        "ALTER TABLE messages DROP COLUMN artifacts",
    ),
    step(
        """CREATE TRIGGER artifact_versions_message_delete AFTER DELETE ON messages
        BEGIN
            DELETE FROM artifact_versions WHERE created_by_message_id = OLD.id;
        END""",
        "DROP TRIGGER IF EXISTS artifact_versions_message_delete",
    ),
    step(
        """CREATE TRIGGER artifacts_version_delete AFTER DELETE ON artifact_versions
        BEGIN
            DELETE FROM artifacts WHERE id = OLD.artifact_id
              AND NOT EXISTS (
                SELECT 1 FROM artifact_versions WHERE artifact_id = OLD.artifact_id);
            UPDATE artifacts
            SET latest_version = (
                SELECT MAX(version) FROM artifact_versions WHERE artifact_id = OLD.artifact_id)
            WHERE id = OLD.artifact_id;
        END""",
        "DROP TRIGGER IF EXISTS artifacts_version_delete",
    ),
    step(
        """CREATE TRIGGER artifacts_conversation_delete AFTER DELETE ON conversations
        BEGIN
            DELETE FROM artifact_versions
            WHERE artifact_id IN (SELECT id FROM artifacts WHERE conversation_id = OLD.id);
            DELETE FROM artifacts WHERE conversation_id = OLD.id;
        END""",
        "DROP TRIGGER IF EXISTS artifacts_conversation_delete",
    ),
]
