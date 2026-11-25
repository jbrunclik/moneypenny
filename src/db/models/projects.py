"""Projects: folders of chats with their own instructions, memory and saved
documents, optionally shared with other family members.

The owner is a member row too, so every scope check is one membership lookup.
A project memory or document is a user_memories / user_documents row with a
project_id (its user_id stays the author). Each member's chats stay theirs:
counts and listings here only ever cover the caller's own chats.

Deletes are soft: the project, its memories and documents share one
deleted_at, so a restore brings exactly those back. Chats are never deleted
with a project - they return to their owners' main lists.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from src.config import Config
from src.db.models.dataclasses import Person, Project, ProjectSummary
from src.db.models.timestamps import from_db, from_db_or_none, to_db
from src.utils.clock import utc_now
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)

# A chat that can be filed under a project: an ordinary chat, mirroring
# is_ordinary() in src/agent/tools/instructions_tool.py
ELIGIBLE_CHAT_SQL = """COALESCE(is_planning, 0) = 0 AND COALESCE(is_agent, 0) = 0
    AND COALESCE(is_sports, 0) = 0 AND COALESCE(is_language, 0) = 0
    AND COALESCE(is_whats_new, 0) = 0 AND standing_type IS NULL
    AND COALESCE(anonymous_mode, 0) = 0"""

_MEMBER_SQL = (
    "EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id = p.id AND pm.user_id = ?)"
)
_SCOPED_TABLES = ("user_memories", "user_documents")


class ProjectWriteError(Exception):
    """A project write the store refused; the message says why."""


class ProjectMixin:
    """Mixin providing project database operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[object, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    if TYPE_CHECKING:

        def _update_where(
            self,
            where: str,
            params: tuple[object, ...],
            set_clause: str,
            set_params: tuple[object, ...],
        ) -> list[str]:
            """Defined in ConversationTrashMixin."""

    def _member_ids(self, conn: sqlite3.Connection, project_id: str) -> list[str]:
        rows = self._execute_with_timing(
            conn,
            "SELECT user_id FROM project_members WHERE project_id = ? ORDER BY added_at, user_id",
            (project_id,),
        ).fetchall()
        return [row["user_id"] for row in rows]

    def _row_to_project(self, conn: sqlite3.Connection, row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"],
            owner_id=row["owner_id"],
            name=row["name"],
            instructions=row["instructions"] or "",
            created_at=from_db(row["created_at"]),
            updated_at=from_db(row["updated_at"]),
            deleted_at=from_db_or_none(row["deleted_at"]),
            member_ids=self._member_ids(conn, row["id"]),
        )

    def create_project(self, owner_id: str, name: str, instructions: str = "") -> Project:
        """Create a project with its owner as the first member.

        Raises:
            ProjectWriteError: the owner already has PROJECTS_MAX_PER_USER live projects
        """
        project_id = str(uuid.uuid4())
        now = to_db(utc_now())
        with self._pool.get_connection() as conn:
            self._execute_with_timing(conn, "BEGIN IMMEDIATE")
            try:
                self._check_owned_cap(conn, owner_id)
                self._execute_with_timing(
                    conn,
                    """INSERT INTO projects (id, owner_id, name, instructions, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (project_id, owner_id, name, instructions, now, now),
                )
                self._execute_with_timing(
                    conn,
                    "INSERT INTO project_members (project_id, user_id, added_at) VALUES (?, ?, ?)",
                    (project_id, owner_id, now),
                )
            except BaseException:
                conn.rollback()
                raise
            conn.commit()
        logger.info("Project created", extra={"project_id": project_id, "user_id": owner_id})
        project = self.get_project(project_id, owner_id)
        if project is None:  # just written in this transaction's commit
            raise ProjectWriteError("the new project could not be read back")
        return project

    def _check_owned_cap(self, conn: sqlite3.Connection, owner_id: str) -> None:
        """Refuse one more live project past PROJECTS_MAX_PER_USER (a create or
        a restore), inside the caller's write transaction."""
        limit = Config.PROJECTS_MAX_PER_USER
        owned = self._execute_with_timing(
            conn,
            "SELECT COUNT(*) FROM projects WHERE owner_id = ? AND deleted_at IS NULL",
            (owner_id,),
        ).fetchone()[0]
        if owned >= limit:
            raise ProjectWriteError(
                f"You already have {owned} projects, the limit is {limit}. Delete one first."
            )

    def get_project(self, project_id: str, user_id: str) -> Project | None:
        """A live project the user is a member of."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                f"SELECT * FROM projects p WHERE p.id = ? AND p.deleted_at IS NULL AND {_MEMBER_SQL}",
                (project_id, user_id),
            ).fetchone()
            return self._row_to_project(conn, row) if row else None

    def list_projects(self, user_id: str) -> list[ProjectSummary]:
        """The live projects the user is a member of, by name, with counts of
        the user's own chats in each (unread: messages not yet shown)."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                f"""SELECT p.*,
                       (SELECT COUNT(*) FROM conversations c
                        WHERE c.project_id = p.id AND c.user_id = ? AND c.deleted_at IS NULL
                       ) AS chat_count,
                       (SELECT COALESCE(SUM(MAX(0, (SELECT COUNT(*) FROM messages m
                                                     WHERE m.conversation_id = c.id)
                                                 - c.read_message_count)), 0)
                        FROM conversations c
                        WHERE c.project_id = p.id AND c.user_id = ? AND c.deleted_at IS NULL
                          AND COALESCE(c.archived, 0) = 0
                       ) AS unread_count
                   FROM projects p
                   WHERE p.deleted_at IS NULL AND {_MEMBER_SQL}
                   ORDER BY p.name COLLATE NOCASE, p.id""",
                (user_id, user_id, user_id),
            ).fetchall()
            return [
                ProjectSummary(
                    project=(project := self._row_to_project(conn, row)),
                    member_names=self._member_names(conn, project.member_ids),
                    chat_count=int(row["chat_count"]),
                    unread_count=int(row["unread_count"]),
                )
                for row in rows
            ]

    def _member_names(self, conn: sqlite3.Connection, user_ids: list[str]) -> list[str]:
        names = []
        for user_id in user_ids:
            row = self._execute_with_timing(
                conn, "SELECT name, email FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if row:
                names.append(row["name"] or row["email"].split("@")[0])
        return names

    def update_project(
        self,
        project_id: str,
        user_id: str,
        *,
        name: str | None = None,
        instructions: str | None = None,
        expected_instructions: str | None = None,
    ) -> bool:
        """Rename (owner only) and/or set the instructions (any member). With
        ``expected_instructions`` the instructions land only while the row
        still holds that text. Returns False when nothing was allowed."""
        sets: list[str] = ["updated_at = ?"]
        params: list[object] = [to_db(utc_now())]
        if name is not None:
            sets.append("name = ?")
            params.append(name)
        if instructions is not None:
            sets.append("instructions = ?")
            params.append(instructions)
        where = f"p.id = ? AND p.deleted_at IS NULL AND {_MEMBER_SQL}"
        params.extend([project_id, user_id])
        if name is not None:
            where += " AND p.owner_id = ?"
            params.append(user_id)
        if expected_instructions is not None:
            where += " AND p.instructions = ?"
            params.append(expected_instructions)
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn, f"UPDATE projects AS p SET {', '.join(sets)} WHERE {where}", tuple(params)
            )
            conn.commit()
            return cursor.rowcount > 0

    def add_project_member(self, project_id: str, owner_id: str, member_id: str) -> bool:
        """The owner adds a family member (idempotent)."""
        with self._pool.get_connection() as conn:
            owned = self._execute_with_timing(
                conn,
                "SELECT 1 FROM projects WHERE id = ? AND owner_id = ? AND deleted_at IS NULL",
                (project_id, owner_id),
            ).fetchone()
            known = self._execute_with_timing(
                conn, "SELECT 1 FROM users WHERE id = ?", (member_id,)
            ).fetchone()
            if not owned or not known:
                return False
            self._execute_with_timing(
                conn,
                """INSERT OR IGNORE INTO project_members (project_id, user_id, added_at)
                   VALUES (?, ?, ?)""",
                (project_id, member_id, to_db(utc_now())),
            )
            self._touch(conn, project_id)
            conn.commit()
        logger.info(
            "Project member added",
            extra={"project_id": project_id, "user_id": owner_id, "member_id": member_id},
        )
        return True

    def remove_project_member(self, project_id: str, actor_id: str, member_id: str) -> bool:
        """The owner removes a member, or a member leaves. The owner never
        leaves their own project. The member's chats in it return to their
        main list; what they wrote stays with the project."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn, "SELECT owner_id FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if not row or member_id == row["owner_id"]:
                return False
            if actor_id not in (row["owner_id"], member_id):
                return False
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM project_members WHERE project_id = ? AND user_id = ?",
                (project_id, member_id),
            )
            self._execute_with_timing(
                conn,
                "UPDATE conversations SET project_id = NULL WHERE project_id = ? AND user_id = ?",
                (project_id, member_id),
            )
            self._touch(conn, project_id)
            conn.commit()
            removed = cursor.rowcount > 0
        if removed:
            logger.info(
                "Project member removed",
                extra={"project_id": project_id, "user_id": actor_id, "member_id": member_id},
            )
        return removed

    def _touch(self, conn: sqlite3.Connection, project_id: str) -> None:
        self._execute_with_timing(
            conn,
            "UPDATE projects SET updated_at = ? WHERE id = ?",
            (to_db(utc_now()), project_id),
        )

    def delete_project(self, project_id: str, owner_id: str) -> bool:
        """Soft-delete a project with its live memories and documents (one
        shared deleted_at); every member's chats return to their main list."""
        now = to_db(utc_now())
        with self._pool.get_connection() as conn:
            self._execute_with_timing(conn, "BEGIN IMMEDIATE")
            try:
                cursor = self._execute_with_timing(
                    conn,
                    """UPDATE projects SET deleted_at = ?, updated_at = ?
                       WHERE id = ? AND owner_id = ? AND deleted_at IS NULL""",
                    (now, now, project_id, owner_id),
                )
                if cursor.rowcount:
                    for table in _SCOPED_TABLES:
                        self._execute_with_timing(
                            conn,
                            f"""UPDATE {table} SET deleted_at = ?
                                WHERE project_id = ? AND deleted_at IS NULL""",
                            (now, project_id),
                        )
                    self._execute_with_timing(
                        conn,
                        "UPDATE conversations SET project_id = NULL WHERE project_id = ?",
                        (project_id,),
                    )
            except BaseException:
                conn.rollback()
                raise
            conn.commit()
            deleted = cursor.rowcount > 0
        if deleted:
            logger.info("Project deleted", extra={"project_id": project_id, "user_id": owner_id})
        return deleted

    def restore_project(self, project_id: str, owner_id: str) -> bool:
        """Bring a deleted project back with the memories and documents that
        were deleted with it (not its chats: they may have moved since).

        Raises:
            ProjectWriteError: the owner already has PROJECTS_MAX_PER_USER live projects
        """
        with self._pool.get_connection() as conn:
            self._execute_with_timing(conn, "BEGIN IMMEDIATE")
            try:
                row = self._execute_with_timing(
                    conn,
                    """SELECT deleted_at FROM projects
                       WHERE id = ? AND owner_id = ? AND deleted_at IS NOT NULL""",
                    (project_id, owner_id),
                ).fetchone()
                if row:
                    self._check_owned_cap(conn, owner_id)
                    for table in _SCOPED_TABLES:
                        self._execute_with_timing(
                            conn,
                            f"UPDATE {table} SET deleted_at = NULL WHERE project_id = ? AND deleted_at = ?",
                            (project_id, row["deleted_at"]),
                        )
                    self._execute_with_timing(
                        conn,
                        "UPDATE projects SET deleted_at = NULL, updated_at = ? WHERE id = ?",
                        (to_db(utc_now()), project_id),
                    )
            except BaseException:
                conn.rollback()
                raise
            conn.commit()
        return row is not None

    def list_deleted_projects(self, owner_id: str) -> list[Project]:
        """The owner's deleted projects inside the retention window, newest first."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM projects WHERE owner_id = ? AND deleted_at IS NOT NULL
                   ORDER BY deleted_at DESC""",
                (owner_id,),
            ).fetchall()
            return [self._row_to_project(conn, row) for row in rows]

    def purge_deleted_projects(self, retention_days: int) -> int:
        """Hard-delete projects deleted more than ``retention_days`` ago with
        their members and memories. Run after the document purge, which
        removes the project's documents and their blobs (they share the
        project's deleted_at, and the same retention)."""
        cutoff = to_db(utc_now() - timedelta(days=retention_days))
        with self._pool.get_connection() as conn:
            ids = [
                row["id"]
                for row in self._execute_with_timing(
                    conn,
                    "SELECT id FROM projects WHERE deleted_at IS NOT NULL AND deleted_at < ?",
                    (cutoff,),
                ).fetchall()
            ]
            for project_id in ids:
                self._execute_with_timing(
                    conn, "DELETE FROM user_memories WHERE project_id = ?", (project_id,)
                )
                self._execute_with_timing(
                    conn, "DELETE FROM project_members WHERE project_id = ?", (project_id,)
                )
                self._execute_with_timing(conn, "DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
        return len(ids)

    def set_conversation_project(self, conv_id: str, user_id: str, project_id: str | None) -> bool:
        """File the user's own ordinary chat under a project they belong to,
        or take it out (``None``). False when that is not allowed."""
        if project_id is not None and self.get_project(project_id, user_id) is None:
            return False
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                f"""UPDATE conversations SET project_id = ?
                    WHERE id = ? AND user_id = ? AND deleted_at IS NULL AND {ELIGIBLE_CHAT_SQL}""",
                (project_id, conv_id, user_id),
            )
            conn.commit()
            moved = cursor.rowcount > 0
        if moved:
            logger.info(
                "Chat moved to project",
                extra={"user_id": user_id, "conversation_id": conv_id, "to": project_id},
            )
        return moved

    def move_conversations(
        self,
        user_id: str,
        project_id: str | None,
        ids: list[str],
        *,
        all_before: datetime | None = None,
        exclude_ids: list[str] | None = None,
    ) -> list[str]:
        """File many of the user's ordinary chats under a project (or take
        them out with None): ``ids``, plus with ``all_before`` every unpinned,
        unarchived main-list chat created before it except ``exclude_ids``
        (the sidebar's Select all). Returns the ids moved."""
        if project_id is not None and self.get_project(project_id, user_id) is None:
            return []
        base = f"user_id = ? AND deleted_at IS NULL AND {ELIGIBLE_CHAT_SQL}"
        picked = f"id IN ({', '.join('?' * len(ids))})" if ids else "0"
        params: list[object] = [user_id, *ids]
        if all_before is not None:
            excluded = exclude_ids or []
            marks = ", ".join("?" * len(excluded)) or "NULL"
            picked = f"""({picked} OR (project_id IS NULL AND COALESCE(pinned, 0) = 0
                AND COALESCE(archived, 0) = 0 AND created_at < ? AND id NOT IN ({marks})))"""
            params.extend([all_before, *excluded])
        moved = self._update_where(
            f"{base} AND {picked}", tuple(params), "project_id = ?", (project_id,)
        )
        logger.info(
            "Chat moved to project",
            extra={"user_id": user_id, "to": project_id, "count": len(moved)},
        )
        return moved

    def project_for_conversation(self, conv_id: str, user_id: str) -> Project | None:
        """The live project the user's chat is filed under, if the user is
        still a member of it."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT project_id FROM conversations WHERE id = ? AND user_id = ?",
                (conv_id, user_id),
            ).fetchone()
        if not row or not row["project_id"]:
            return None
        return self.get_project(row["project_id"], user_id)

    def projects_version(self, user_id: str) -> str:
        """Changes whenever the user's project list does (a project added,
        renamed, shared, left, deleted, its instructions edited): every such
        write bumps the project's updated_at or the user's membership count.
        The sync poll compares it to reload the sidebar's projects."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                f"""SELECT COUNT(*) AS n, COALESCE(MAX(p.updated_at), '') AS latest,
                           COALESCE(SUM(p.deleted_at IS NOT NULL), 0) AS gone
                    FROM projects p WHERE {_MEMBER_SQL}""",
                (user_id,),
            ).fetchone()
        return f"{row['n']}:{row['gone']}:{row['latest']}"

    def list_people(self, exclude_user_id: str) -> list[Person]:
        """The deployment's other users: the family to share with."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                "SELECT id, name, email, picture FROM users WHERE id != ? ORDER BY name, email",
                (exclude_user_id,),
            ).fetchall()
        return [
            Person(row["id"], row["name"] or row["email"].split("@")[0], row["picture"])
            for row in rows
        ]
