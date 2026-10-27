"""Embeddings storage mixin (semantic recall over memories and messages).

Vectors are packed float32 blobs (src/utils/embeddings.py); similarity search
is brute-force cosine in Python - at family scale (a few thousand vectors per
user) that is faster and simpler than a vector-index extension.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.db.models.timestamps import to_db
from src.utils.clock import utc_now
from src.utils.embeddings import embed_text, pack_vector
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class EmbeddingsMixin:
    """Mixin providing embedding-vector storage operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def upsert_embedding(
        self,
        user_id: str,
        kind: str,
        ref_id: str,
        model: str,
        dim: int,
        vector: bytes,
    ) -> None:
        """Insert or replace the embedding for (kind, ref_id)."""
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO embeddings (id, user_id, kind, ref_id, model, dim, vector, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(kind, ref_id) DO UPDATE SET
                       user_id = excluded.user_id,
                       model = excluded.model,
                       dim = excluded.dim,
                       vector = excluded.vector,
                       created_at = excluded.created_at""",
                (
                    str(uuid.uuid4()),
                    user_id,
                    kind,
                    ref_id,
                    model,
                    dim,
                    vector,
                    to_db(utc_now(), "local", conn),
                ),
            )
            conn.commit()

    def embed_and_store_async(self, user_id: str, kind: str, ref_id: str, text: str) -> None:
        """Embed text and upsert it into the embeddings table on a daemon thread.

        Fire-and-forget: failures are logged, never raised - embedding freshness
        is best-effort and the write path must not block on the embedding API.
        """
        if not Config.EMBEDDINGS_ENABLED:
            return

        def _work() -> None:
            vec = embed_text(text)
            if vec is None:
                return
            try:
                self.upsert_embedding(
                    user_id, kind, ref_id, Config.EMBEDDING_MODEL, len(vec), pack_vector(vec)
                )
            except Exception:
                logger.warning(
                    "Failed to store embedding",
                    extra={"kind": kind, "ref_id": ref_id},
                    exc_info=True,
                )

        threading.Thread(target=_work, daemon=True, name=f"embed-{kind}").start()

    def get_embeddings(self, user_id: str, kind: str) -> list[tuple[str, int, bytes]]:
        """All (ref_id, dim, vector) rows for a user and kind."""
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "SELECT ref_id, dim, vector FROM embeddings WHERE user_id = ? AND kind = ?",
                (user_id, kind),
            )
            return [(row[0], row[1], row[2]) for row in cursor.fetchall()]

    def get_message_rows_for_ids(
        self, user_id: str, message_ids: list[str]
    ) -> list[tuple[str, str, str, str, str]]:
        """Resolve message ids to (message_id, conversation_id, content,
        created_at, conversation_title), scoped to the user's conversations.

        Used to render semantic search hits; ids whose message or conversation
        no longer exists simply drop out (embeddings may outlive their rows).
        """
        if not message_ids:
            return []
        placeholders = ",".join("?" for _ in message_ids)
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                f"""SELECT m.id, m.conversation_id, m.content, m.created_at, c.title
                    FROM messages m
                    JOIN conversations c ON c.id = m.conversation_id
                    WHERE c.user_id = ? AND c.deleted_at IS NULL
                      AND m.id IN ({placeholders})""",  # placeholders only
                (user_id, *message_ids),
            )
            rows = cursor.fetchall()
        by_id = {row[0]: (row[0], row[1], row[2], row[3], row[4]) for row in rows}
        # Preserve the caller's (similarity-ranked) order
        return [by_id[message_id] for message_id in message_ids if message_id in by_id]

    def delete_embedding(self, kind: str, ref_id: str) -> None:
        """Remove the embedding for (kind, ref_id), if any."""
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                "DELETE FROM embeddings WHERE kind = ? AND ref_id = ?",
                (kind, ref_id),
            )
            conn.commit()
