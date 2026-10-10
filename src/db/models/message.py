"""Message database operations mixin.

Message CRUD: add, fetch, update and delete messages. Pagination lives in
message_pagination.py, file/thumbnail handling in message_files.py.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.api.schemas.common import MessageRole
from src.db.models.dataclasses import Message
from src.db.models.helpers import (
    delete_message_blobs,
    extract_file_metadata,
    save_file_to_blob_store,
)
from src.db.models.message_rows import row_to_message
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


def _store_message_payload(
    message_id: str,
    files: list[dict[str, Any]],
    sources: list[dict[str, str]] | None,
    generated_images: list[dict[str, str]] | None,
    tool_outputs: list[dict[str, str]] | None,
) -> tuple[list[dict[str, Any]], str | None, str | None, str | None, str | None]:
    """Save file blobs; return (files_metadata, files, sources, images, tool_outputs JSON)."""
    # Extract metadata and save binary data to blob store
    files_metadata: list[dict[str, Any]] = []
    for idx, file_data in enumerate(files):
        # Save file data and thumbnail to blob store
        save_file_to_blob_store(message_id, idx, file_data)
        # Keep only metadata in the database
        files_metadata.append(extract_file_metadata(file_data))

    files_json = json.dumps(files_metadata) if files_metadata else None
    sources_json = json.dumps(sources) if sources else None
    generated_images_json = json.dumps(generated_images) if generated_images else None
    tool_outputs_json = json.dumps(tool_outputs, ensure_ascii=False) if tool_outputs else None
    return files_metadata, files_json, sources_json, generated_images_json, tool_outputs_json


def _json_or_none(value: Any) -> str | None:
    return json.dumps(value, ensure_ascii=False) if value else None


class MessageMixin:
    """Mixin providing Message-related database operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def delete_message(self, message_id: str, user_id: str) -> bool:
        """Delete a message by ID.

        Verifies that the message belongs to a conversation owned by the user.
        Also deletes associated blobs (files, thumbnails).
        Note: Message costs are intentionally preserved for accurate reporting.

        Args:
            message_id: The message ID to delete
            user_id: The user ID (for ownership verification)

        Returns:
            True if the message was deleted, False if not found or not owned
        """
        with self._pool.get_connection() as conn:
            # Verify user owns the conversation containing this message
            row = self._execute_with_timing(
                conn,
                """
                SELECT m.id FROM messages m
                JOIN conversations c ON m.conversation_id = c.id
                WHERE m.id = ? AND c.user_id = ?
                """,
                (message_id, user_id),
            ).fetchone()

            if not row:
                return False

            # Delete the message row FIRST: a crash between the two deletes
            # then leaves only a harmless orphaned blob, not a live row
            # pointing at deleted file data (404 on file serve)
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM messages WHERE id = ?",
                (message_id,),
            )
            conn.commit()

            # Delete associated blobs (files, thumbnails)
            delete_message_blobs(message_id)
            return cursor.rowcount > 0

    def delete_messages_after(
        self,
        conversation_id: str,
        user_id: str,
        message_id: str,
        inclusive: bool,
    ) -> int:
        """Truncate a conversation's tail: delete every message after
        `message_id` (and the message itself when `inclusive`).

        The shared primitive behind edit-and-resend and regenerate. Ordering
        matches insertion (created_at with rowid as tiebreak). Returns the
        number of deleted messages; 0 when the target message doesn't exist
        in this conversation or the user doesn't own it.
        """
        with self._pool.get_connection() as conn:
            target = self._execute_with_timing(
                conn,
                """
                SELECT m.rowid AS row_id, m.created_at FROM messages m
                JOIN conversations c ON m.conversation_id = c.id
                WHERE m.id = ? AND m.conversation_id = ? AND c.user_id = ?
                """,
                (message_id, conversation_id, user_id),
            ).fetchone()
            if not target:
                return 0

            comparison = ">=" if inclusive else ">"
            doomed = self._execute_with_timing(
                conn,
                f"""
                SELECT id FROM messages
                WHERE conversation_id = ?
                  AND (created_at > ? OR (created_at = ? AND rowid {comparison} ?))
                """,
                (conversation_id, target["created_at"], target["created_at"], target["row_id"]),
            ).fetchall()
            doomed_ids = [row["id"] for row in doomed]
            if not doomed_ids:
                return 0

            placeholders = ",".join("?" * len(doomed_ids))
            self._execute_with_timing(
                conn,
                f"DELETE FROM messages WHERE id IN ({placeholders})",
                tuple(doomed_ids),
            )
            conn.commit()

        # Blobs go second: a crash between the deletes leaves harmless
        # orphaned blobs, never live rows pointing at deleted data
        for doomed_id in doomed_ids:
            delete_message_blobs(doomed_id)

        logger.info(
            "Truncated conversation tail",
            extra={
                "conversation_id": conversation_id,
                "message_id": message_id,
                "inclusive": inclusive,
                "deleted": len(doomed_ids),
            },
        )
        return len(doomed_ids)

    def add_message(
        self,
        conversation_id: str,
        role: MessageRole | str,
        content: str,
        files: list[dict[str, Any]] | None = None,
        sources: list[dict[str, str]] | None = None,
        generated_images: list[dict[str, str]] | None = None,
        language: str | None = None,
        message_id: str | None = None,
        tool_outputs: list[dict[str, str]] | None = None,
        stop_reason: str | None = None,
        annotations: list[dict[str, Any]] | None = None,
        grounding: dict[str, Any] | None = None,
        research: dict[str, Any] | None = None,
        action: dict[str, Any] | None = None,
    ) -> Message:
        """Add a message to a conversation.

        Files are stored in a separate blob store (files.db) to keep the main
        database small and fast. Only file metadata is stored in the messages table.

        Args:
            conversation_id: The conversation ID
            role: MessageRole.USER or MessageRole.ASSISTANT (also accepts "user"/"assistant" strings)
            content: Plain text message
            files: Optional list of file attachments (with 'data' and optional 'thumbnail')
            sources: Optional list of web sources (for assistant messages)
            generated_images: Optional list of generated image metadata (for assistant messages)
            language: Optional ISO 639-1 language code (e.g., "en", "cs") for TTS
            message_id: Optional pre-generated message ID (for streaming recovery)
            tool_outputs: Optional per-call tool output digests (assistant messages)
            stop_reason: "user" when the user pressed Stop (partial reply kept)
            annotations: Optional grounding-check claim annotations
            grounding: Optional grounding summary for the footer
            research: Optional deep-research offer or run data
            action: What a user message sent on the user's behalf was

        Returns:
            The created Message
        """
        # Normalize role to enum if passed as string
        if isinstance(role, str) and not isinstance(role, MessageRole):
            role = MessageRole(role)
        msg_id = message_id or str(uuid.uuid4())
        now = datetime.now()
        files = files or []

        files_metadata, files_json, sources_json, generated_images_json, tool_outputs_json = (
            _store_message_payload(msg_id, files, sources, generated_images, tool_outputs)
        )
        logger.debug(
            "Adding message",
            extra={
                "conversation_id": conversation_id,
                "message_id": msg_id,
                "role": role,
                "content_length": len(content),
                "file_count": len(files),
                "has_sources": bool(sources),
                "has_generated_images": bool(generated_images),
            },
        )

        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                """INSERT INTO messages (id, conversation_id, role, content, files, sources, generated_images, language, created_at, tool_outputs, stop_reason, annotations, grounding, research, action)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    msg_id,
                    conversation_id,
                    role,
                    content,
                    files_json,
                    sources_json,
                    generated_images_json,
                    language,
                    now.isoformat(),
                    tool_outputs_json,
                    stop_reason,
                    _json_or_none(annotations),
                    _json_or_none(grounding),
                    _json_or_none(research),
                    _json_or_none(action),
                ),
            )
            # Update conversation's updated_at
            self._execute_with_timing(
                conn,
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now.isoformat(), conversation_id),
            )
            conn.commit()

        logger.debug(
            "Message added", extra={"message_id": msg_id, "conversation_id": conversation_id}
        )
        self._schedule_message_embedding(msg_id, conversation_id, content)
        return Message(
            id=msg_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=now,
            files=files_metadata,
            sources=sources,
            generated_images=generated_images,
            language=language,
            tool_outputs=tool_outputs,
            annotations=annotations,
            grounding=grounding,
            research=research,
            action=action,
        )

    def set_message_created_at(self, message_id: str, created_at: datetime) -> None:
        """Re-stamp a message (moves it in the conversation's order)."""
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                "UPDATE messages SET created_at = ? WHERE id = ?",
                (created_at.isoformat(), message_id),
            )
            conn.commit()

    def set_message_research(self, message_id: str, research: dict[str, Any] | None) -> None:
        """Replace a message's deep-research data (offer status changes)."""
        with self._pool.get_connection() as conn:
            self._execute_with_timing(
                conn,
                "UPDATE messages SET research = ? WHERE id = ?",
                (_json_or_none(research), message_id),
            )
            conn.commit()

    def decide_research_offer(
        self, message_id: str, status_path: str, research: dict[str, Any]
    ) -> bool:
        """Write the decided research data only if the offer at status_path is
        still "offered" (one atomic UPDATE). False when it was decided meanwhile."""
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE messages SET research = ? WHERE id = ? "
                "AND json_extract(research, ?) = 'offered'",
                (_json_or_none(research), message_id, status_path),
            )
            conn.commit()
            return bool(cursor.rowcount == 1)

    def find_open_research_offers(self, conversation_id: str) -> list[Message]:
        """Messages in a conversation whose deep-research offer is still open
        (an initial offer, or a report's follow-up offer)."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM messages WHERE conversation_id = ? AND research IS NOT NULL
                   AND (json_extract(research, '$.offer.status') = 'offered'
                        OR json_extract(research, '$.run.followup.status') = 'offered')""",
                (conversation_id,),
            ).fetchall()
        return [row_to_message(row) for row in rows]

    def _schedule_message_embedding(
        self, message_id: str, conversation_id: str, content: str
    ) -> None:
        """Fire-and-forget semantic-recall embedding for a saved message.

        This is the single seam every message write flows through (batch chat,
        streaming, agents, programs), so hooking here keeps the embedding
        write-path complete without touching each save site. The embed itself
        runs on a daemon thread; this only resolves the conversation owner.
        """
        from src.config import Config

        if not Config.EMBEDDINGS_ENABLED or not content.strip():
            return
        try:
            with self._pool.get_connection() as conn:
                row = self._execute_with_timing(
                    conn,
                    "SELECT user_id FROM conversations WHERE id = ?",
                    (conversation_id,),
                ).fetchone()
            if not row:
                return
            import src.utils.embeddings as embeddings_util

            embeddings_util.embed_and_store_async(row["user_id"], "message", message_id, content)
        except Exception:
            # Embedding freshness is best-effort; a failure must never break
            # the message save
            logger.warning(
                "Failed to schedule message embedding",
                extra={"message_id": message_id},
                exc_info=True,
            )

    def get_messages(self, conversation_id: str) -> list[Message]:
        """Get all messages for a conversation."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
                (conversation_id,),
            ).fetchall()

            return [row_to_message(row) for row in rows]

    def get_message_by_id(self, message_id: str) -> Message | None:
        """Get a single message by its ID."""
        with self._pool.get_connection() as conn:
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM messages WHERE id = ?",
                (message_id,),
            ).fetchone()

            if not row:
                return None

            return row_to_message(row)

    def update_message_content(
        self,
        message_id: str,
        content: str,
        files: list[dict[str, Any]] | None = None,
        sources: list[dict[str, str]] | None = None,
        generated_images: list[dict[str, str]] | None = None,
        language: str | None = None,
        tool_outputs: list[dict[str, str]] | None = None,
        stop_reason: str | None = None,
        annotations: list[dict[str, Any]] | None = None,
        grounding: dict[str, Any] | None = None,
        research: dict[str, Any] | None = None,
    ) -> Message | None:
        """Update an existing message's content fields.

        Used to fill in a placeholder message saved at stream start with the
        final content once streaming completes.

        Args:
            message_id: The message ID to update
            content: The message content text
            files: Optional list of file attachments (with 'data' and optional 'thumbnail')
            sources: Optional list of web sources
            generated_images: Optional list of generated image metadata
            language: Optional ISO 639-1 language code
            tool_outputs: Optional per-call tool output digests
            stop_reason: "user" when the user pressed Stop (partial reply kept)
            annotations: Optional grounding-check claim annotations
            grounding: Optional grounding summary for the footer
            research: Optional deep-research offer or run data

        Returns:
            The updated Message, or None if the message no longer exists
        """
        files = files or []

        _, files_json, sources_json, generated_images_json, tool_outputs_json = (
            _store_message_payload(message_id, files, sources, generated_images, tool_outputs)
        )
        now = datetime.now()

        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                """UPDATE messages
                   SET content = ?, files = ?, sources = ?, generated_images = ?, language = ?,
                       tool_outputs = ?, stop_reason = ?, annotations = ?, grounding = ?,
                       research = ?
                   WHERE id = ?""",
                (
                    content,
                    files_json,
                    sources_json,
                    generated_images_json,
                    language,
                    tool_outputs_json,
                    stop_reason,
                    _json_or_none(annotations),
                    _json_or_none(grounding),
                    _json_or_none(research),
                    message_id,
                ),
            )

            if cursor.rowcount == 0:
                return None

            # Update conversation's updated_at
            self._execute_with_timing(
                conn,
                """UPDATE conversations SET updated_at = ?
                   WHERE id = (SELECT conversation_id FROM messages WHERE id = ?)""",
                (now.isoformat(), message_id),
            )
            conn.commit()

            # Fetch the updated message to return
            row = self._execute_with_timing(
                conn,
                "SELECT * FROM messages WHERE id = ?",
                (message_id,),
            ).fetchone()

        if not row:
            return None

        self._schedule_message_embedding(message_id, row["conversation_id"], content)

        return row_to_message(row)

    def delete_message_by_id(self, message_id: str) -> bool:
        """Delete a message by ID without ownership checks.

        Lightweight internal cleanup for placeholder messages that have no
        blobs or associated data.

        Args:
            message_id: The message ID to delete

        Returns:
            True if the message was deleted, False if not found
        """
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM messages WHERE id = ?",
                (message_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
