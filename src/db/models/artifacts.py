"""Artifact database operations mixin.

Artifacts are agent-made HTML/JS pages shown inline under a reply, versioned per
edit (docs/superpowers/specs/2026-10-11-inline-artifacts-design.md). Cleanup when
messages or conversations are deleted is done by triggers (migration 0065).
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.db.models.dataclasses import Artifact, ArtifactVersion
from src.utils.datetime_utils import utcnow_naive
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)

_ARTIFACT_ID_BYTES = 9


def _row_to_artifact(row: sqlite3.Row) -> Artifact:
    return Artifact(
        id=row["id"],
        conversation_id=row["conversation_id"],
        user_id=row["user_id"],
        title=row["title"],
        latest_version=row["latest_version"],
        state=json.loads(row["state"]) if row["state"] else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_version(row: sqlite3.Row) -> ArtifactVersion:
    return ArtifactVersion(
        artifact_id=row["artifact_id"],
        version=row["version"],
        html=row["html"],
        created_by_message_id=row["created_by_message_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class ArtifactMixin:
    """Mixin providing artifact and artifact-version operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def create_artifact(
        self, conversation_id: str, user_id: str, title: str, html: str
    ) -> tuple[Artifact, ArtifactVersion]:
        """Create an artifact and its version 1 in one write."""
        art_id = secrets.token_urlsafe(_ARTIFACT_ID_BYTES)
        now = utcnow_naive()
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO artifacts (id, conversation_id, user_id, title, latest_version,
                   created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)""",
                (art_id, conversation_id, user_id, title, now.isoformat(), now.isoformat()),
            )
            self._insert_version(conn, art_id, 1, html, now)
            conn.commit()
        artifact = Artifact(art_id, conversation_id, user_id, title, 1, None, now, now)
        return artifact, ArtifactVersion(art_id, 1, html, None, now)

    def _insert_version(
        self, conn: sqlite3.Connection, art_id: str, version: int, html: str, now: datetime
    ) -> None:
        self._execute_with_timing(
            conn,
            """INSERT INTO artifact_versions (artifact_id, version, html, created_at)
               VALUES (?, ?, ?, ?)""",
            (art_id, version, html, now.isoformat()),
        )

    def add_artifact_version(
        self, artifact_id: str, html: str, title: str | None = None
    ) -> ArtifactVersion:
        """Add the next version; also renames the artifact when `title` is given."""
        now = utcnow_naive()
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT MAX(version) AS v FROM artifact_versions WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
            version = int(row["v"] or 0) + 1
            self._insert_version(conn, artifact_id, version, html, now)
            self._execute_with_timing(
                conn,
                """UPDATE artifacts SET latest_version = ?, updated_at = ?,
                   title = COALESCE(?, title) WHERE id = ?""",
                (version, now.isoformat(), title, artifact_id),
            )
            conn.commit()
        return ArtifactVersion(artifact_id, version, html, None, now)

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        """An artifact by id, or None."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn, "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
        return _row_to_artifact(row) if row else None

    def get_artifact_for_user(self, artifact_id: str, user_id: str) -> Artifact | None:
        """An artifact whose conversation the user owns, or None."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                """SELECT a.* FROM artifacts a JOIN conversations c ON a.conversation_id = c.id
                   WHERE a.id = ? AND c.user_id = ?""",
                (artifact_id, user_id),
            ).fetchone()
        return _row_to_artifact(row) if row else None

    def get_artifact_version(self, artifact_id: str, version: int) -> ArtifactVersion | None:
        """One version of an artifact, or None."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM artifact_versions WHERE artifact_id = ? AND version = ?",
                (artifact_id, version),
            ).fetchone()
        return _row_to_version(row) if row else None

    def count_conversation_artifacts(self, conversation_id: str) -> int:
        """How many artifacts a conversation has."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT COUNT(*) AS n FROM artifacts WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return int(row["n"])

    def set_artifact_state(self, artifact_id: str, state: dict[str, Any] | None) -> None:
        """Replace an artifact's saved state (None clears it)."""
        payload = json.dumps(state) if state is not None else None
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                "UPDATE artifacts SET state = ?, updated_at = ? WHERE id = ?",
                (payload, utcnow_naive().isoformat(), artifact_id),
            )
            conn.commit()

    def link_artifact_versions(self, message_id: str, refs: list[tuple[str, int]]) -> None:
        """Record which reply made these versions (their cleanup follows the message)."""
        if not refs:
            return
        with self._pool.get_connection() as conn:
            for artifact_id, version in refs:
                self._execute_with_timing(
                    conn,
                    """UPDATE artifact_versions SET created_by_message_id = ?
                       WHERE artifact_id = ? AND version = ?""",
                    (message_id, artifact_id, version),
                )
            conn.commit()
