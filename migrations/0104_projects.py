"""Projects (Nov 2026): folders of chats with their own instructions, memory and
saved documents, optionally shared with other family members.

A project memory or document is an ordinary user_memories / user_documents
row with a project_id; its user_id stays the author. Personal queries filter
project_id IS NULL. The added project_id columns carry no REFERENCES clause
(foreign keys are not enforced here, and a column with one cannot be
dropped on rollback); the store keeps them consistent.
"""

from yoyo import step

__depends__ = {"0103_user_documents"}

_SCOPED_TABLES = ("conversations", "user_memories", "user_documents")

steps = [
    step(
        """CREATE TABLE projects (
               id TEXT PRIMARY KEY,
               owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
               name TEXT NOT NULL,
               instructions TEXT NOT NULL DEFAULT '',
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL,
               deleted_at TEXT
           )""",
        "DROP TABLE projects",
    ),
    step(
        """CREATE TABLE project_members (
               project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
               user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
               added_at TEXT NOT NULL,
               PRIMARY KEY (project_id, user_id)
           )""",
        "DROP TABLE project_members",
    ),
    step(
        "CREATE INDEX idx_project_members_user ON project_members(user_id)",
        "DROP INDEX idx_project_members_user",
    ),
    *[
        step(
            f"ALTER TABLE {table} ADD COLUMN project_id TEXT",
            f"ALTER TABLE {table} DROP COLUMN project_id",
        )
        for table in _SCOPED_TABLES
    ],
    step(
        """CREATE INDEX idx_conversations_project
           ON conversations(project_id, updated_at DESC) WHERE project_id IS NOT NULL""",
        "DROP INDEX idx_conversations_project",
    ),
    step(
        """CREATE INDEX idx_user_memories_project
           ON user_memories(project_id, updated_at DESC)
           WHERE deleted_at IS NULL AND project_id IS NOT NULL""",
        "DROP INDEX idx_user_memories_project",
    ),
    step(
        """CREATE INDEX idx_user_documents_project
           ON user_documents(project_id, deleted_at) WHERE project_id IS NOT NULL""",
        "DROP INDEX idx_user_documents_project",
    ),
]
