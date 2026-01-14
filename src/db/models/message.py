"""Message database operations mixin.

Contains all methods for Message entity management including:
- CRUD operations
- Pagination (cursor-based, bi-directional)
- File/thumbnail handling
"""

from __future__ import annotations

import base64
import json
import sqlite3
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.api.schemas import MessageRole, PaginationDirection, ThumbnailStatus
from src.db.blob_store import get_blob_store
from src.db.models.dataclasses import Message, MessagePagination
from src.db.models.helpers import (
    build_cursor,
    delete_message_blobs,
    extract_file_metadata,
    make_thumbnail_key,
    parse_cursor,
    save_file_to_blob_store,
)
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


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

            # Delete associated blobs (files, thumbnails)
            delete_message_blobs(message_id)

            # Delete the message
            cursor = self._execute_with_timing(
                conn,
                "DELETE FROM messages WHERE id = ?",
                (message_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def add_message(
        self,
        conversation_id: str,
        role: MessageRole | str,
        content: str,
        files: list[dict[str, Any]] | None = None,
        sources: list[dict[str, str]] | None = None,
        generated_images: list[dict[str, str]] | None = None,
        language: str | None = None,
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

        Returns:
            The created Message
        """
        # Normalize role to enum if passed as string
        if isinstance(role, str) and not isinstance(role, MessageRole):
            role = MessageRole(role)
        msg_id = str(uuid.uuid4())
        now = datetime.now()
        files = files or []

        # Extract metadata and save binary data to blob store
        files_metadata: list[dict[str, Any]] = []
        for idx, file_data in enumerate(files):
            # Save file data and thumbnail to blob store
            save_file_to_blob_store(msg_id, idx, file_data)
            # Keep only metadata in the database
            files_metadata.append(extract_file_metadata(file_data))

        files_json = json.dumps(files_metadata) if files_metadata else None
        sources_json = json.dumps(sources) if sources else None
        generated_images_json = json.dumps(generated_images) if generated_images else None
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
                """INSERT INTO messages (id, conversation_id, role, content, files, sources, generated_images, language, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        )

    def get_messages(self, conversation_id: str) -> list[Message]:
        """Get all messages for a conversation."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
                (conversation_id,),
            ).fetchall()

            return [
                Message(
                    id=row["id"],
                    conversation_id=row["conversation_id"],
                    role=MessageRole(row["role"]),
                    content=row["content"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    files=json.loads(row["files"]) if row["files"] else [],
                    sources=json.loads(row["sources"]) if row["sources"] else None,
                    generated_images=json.loads(row["generated_images"])
                    if row["generated_images"]
                    else None,
                    language=row["language"],
                )
                for row in rows
            ]

    def get_messages_paginated(
        self,
        conversation_id: str,
        limit: int = 50,
        cursor: str | None = None,
        direction: PaginationDirection = PaginationDirection.OLDER,
    ) -> tuple[list[Message], MessagePagination]:
        """Get messages for a conversation with cursor-based pagination.

        By default, returns the newest messages (no cursor) or messages
        older/newer than the cursor position.

        Args:
            conversation_id: The conversation ID
            limit: Maximum number of messages to return
            cursor: Optional cursor from previous page (format: '{created_at}:{id}')
            direction: PaginationDirection.OLDER to get messages before cursor,
                      PaginationDirection.NEWER for after

        Returns:
            Tuple of:
            - List of Message objects (oldest first within the returned page)
            - MessagePagination info with cursors and flags
        """
        with self._pool.get_connection() as conn:
            # Get total count
            total_row = self._execute_with_timing(
                conn,
                "SELECT COUNT(*) as count FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            total_count = int(total_row["count"]) if total_row else 0

            if cursor:
                cursor_timestamp, cursor_id = parse_cursor(cursor)

                if direction == PaginationDirection.OLDER:
                    # Fetch messages OLDER than cursor (created_at < cursor_timestamp)
                    # Order by created_at DESC to get the ones just before cursor
                    rows = self._execute_with_timing(
                        conn,
                        """SELECT * FROM messages
                           WHERE conversation_id = ?
                             AND (created_at < ? OR (created_at = ? AND id < ?))
                           ORDER BY created_at DESC, id DESC
                           LIMIT ?""",
                        (conversation_id, cursor_timestamp, cursor_timestamp, cursor_id, limit + 1),
                    ).fetchall()
                else:  # direction == PaginationDirection.NEWER
                    # Fetch messages NEWER than cursor (created_at > cursor_timestamp)
                    # Order by created_at ASC to get the ones just after cursor
                    rows = self._execute_with_timing(
                        conn,
                        """SELECT * FROM messages
                           WHERE conversation_id = ?
                             AND (created_at > ? OR (created_at = ? AND id > ?))
                           ORDER BY created_at ASC, id ASC
                           LIMIT ?""",
                        (conversation_id, cursor_timestamp, cursor_timestamp, cursor_id, limit + 1),
                    ).fetchall()
            else:
                # No cursor: return newest messages (for initial load)
                # Order by created_at DESC to get newest first, then reverse for display
                rows = self._execute_with_timing(
                    conn,
                    """SELECT * FROM messages
                       WHERE conversation_id = ?
                       ORDER BY created_at DESC, id DESC
                       LIMIT ?""",
                    (conversation_id, limit + 1),
                ).fetchall()

            # Check if there are more in the direction we're paginating
            has_more_in_direction = len(rows) > limit
            if has_more_in_direction:
                rows = rows[:limit]

            # Convert rows to Message objects
            messages = [
                Message(
                    id=row["id"],
                    conversation_id=row["conversation_id"],
                    role=MessageRole(row["role"]),
                    content=row["content"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    files=json.loads(row["files"]) if row["files"] else [],
                    sources=json.loads(row["sources"]) if row["sources"] else None,
                    generated_images=json.loads(row["generated_images"])
                    if row["generated_images"]
                    else None,
                    language=row["language"],
                )
                for row in rows
            ]

            # For display, we want messages in chronological order (oldest first)
            # When loading older or initial (newest first in query), we need to reverse
            if not cursor or direction == PaginationDirection.OLDER:
                messages = list(reversed(messages))

            # Build pagination info
            if messages:
                # The oldest message in results becomes the "older_cursor"
                first_msg = messages[0]
                older_cursor = build_cursor(first_msg.created_at.isoformat(), first_msg.id)

                # The newest message in results becomes the "newer_cursor"
                last_msg = messages[-1]
                newer_cursor = build_cursor(last_msg.created_at.isoformat(), last_msg.id)
            else:
                older_cursor = None
                newer_cursor = None

            # Determine has_older and has_newer
            if not cursor:
                # Initial load (newest messages): has_older if we got more, has_newer is False
                has_older = has_more_in_direction
                has_newer = False
            elif direction == PaginationDirection.OLDER:
                # Loading older: has_older if we got more, need to check has_newer separately
                has_older = has_more_in_direction
                # There are newer messages if we had a cursor (we came from somewhere)
                has_newer = True
            else:  # direction == PaginationDirection.NEWER
                # Loading newer: has_newer if we got more, has_older is True (we came from somewhere)
                has_newer = has_more_in_direction
                has_older = True

            pagination = MessagePagination(
                older_cursor=older_cursor if has_older else None,
                newer_cursor=newer_cursor if has_newer else None,
                has_older=has_older,
                has_newer=has_newer,
                total_count=total_count,
            )

            return messages, pagination

    def get_messages_around(
        self,
        conversation_id: str,
        message_id: str,
        before_limit: int = 25,
        after_limit: int = 25,
    ) -> tuple[list[Message], MessagePagination] | None:
        """Get messages around a specific message.

        Loads messages before and after the target message to create a "window"
        centered on the target. Used for efficient search result navigation.

        Args:
            conversation_id: The conversation ID
            message_id: The target message ID to center around
            before_limit: Number of messages to load before the target (inclusive)
            after_limit: Number of messages to load after the target

        Returns:
            Tuple of (messages, pagination) or None if message not found.
            Messages are returned in chronological order (oldest first).
            Pagination includes both older_cursor and newer_cursor for
            bi-directional pagination from the loaded window.
        """
        with self._pool.get_connection() as conn:
            # Get total count
            total_row = self._execute_with_timing(
                conn,
                "SELECT COUNT(*) as count FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            total_count = int(total_row["count"]) if total_row else 0

            # Get the target message to verify it exists and get its timestamp
            target_row = self._execute_with_timing(
                conn,
                "SELECT id, created_at FROM messages WHERE id = ? AND conversation_id = ?",
                (message_id, conversation_id),
            ).fetchone()

            if not target_row:
                return None

            target_timestamp = target_row["created_at"]
            target_id = target_row["id"]

            # Get messages before and including the target
            # (created_at < target) OR (created_at = target AND id <= target_id)
            # Order DESC to get the closest ones, then reverse
            before_rows = self._execute_with_timing(
                conn,
                """SELECT * FROM messages
                   WHERE conversation_id = ?
                     AND (created_at < ? OR (created_at = ? AND id <= ?))
                   ORDER BY created_at DESC, id DESC
                   LIMIT ?""",
                (conversation_id, target_timestamp, target_timestamp, target_id, before_limit + 1),
            ).fetchall()

            # Check if there are older messages beyond what we fetched
            has_older = len(before_rows) > before_limit
            if has_older:
                before_rows = before_rows[:before_limit]

            # Get messages after the target (excluding target itself)
            # (created_at > target) OR (created_at = target AND id > target_id)
            after_rows = self._execute_with_timing(
                conn,
                """SELECT * FROM messages
                   WHERE conversation_id = ?
                     AND (created_at > ? OR (created_at = ? AND id > ?))
                   ORDER BY created_at ASC, id ASC
                   LIMIT ?""",
                (conversation_id, target_timestamp, target_timestamp, target_id, after_limit + 1),
            ).fetchall()

            # Check if there are newer messages beyond what we fetched
            has_newer = len(after_rows) > after_limit
            if has_newer:
                after_rows = after_rows[:after_limit]

            # Combine: reverse before_rows (they're DESC) + after_rows (already ASC)
            all_rows = list(reversed(before_rows)) + list(after_rows)

            # Convert to Message objects
            messages = [
                Message(
                    id=row["id"],
                    conversation_id=row["conversation_id"],
                    role=MessageRole(row["role"]),
                    content=row["content"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    files=json.loads(row["files"]) if row["files"] else [],
                    sources=json.loads(row["sources"]) if row["sources"] else None,
                    generated_images=json.loads(row["generated_images"])
                    if row["generated_images"]
                    else None,
                    language=row["language"],
                )
                for row in all_rows
            ]

            # Build pagination cursors
            if messages:
                first_msg = messages[0]
                older_cursor = build_cursor(first_msg.created_at.isoformat(), first_msg.id)

                last_msg = messages[-1]
                newer_cursor = build_cursor(last_msg.created_at.isoformat(), last_msg.id)
            else:
                older_cursor = None
                newer_cursor = None

            pagination = MessagePagination(
                older_cursor=older_cursor if has_older else None,
                newer_cursor=newer_cursor if has_newer else None,
                has_older=has_older,
                has_newer=has_newer,
                total_count=total_count,
            )

            return messages, pagination

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

            return Message(
                id=row["id"],
                conversation_id=row["conversation_id"],
                role=MessageRole(row["role"]),
                content=row["content"],
                created_at=datetime.fromisoformat(row["created_at"]),
                files=json.loads(row["files"]) if row["files"] else [],
                sources=json.loads(row["sources"]) if row["sources"] else None,
                generated_images=json.loads(row["generated_images"])
                if row["generated_images"]
                else None,
                language=row["language"],
            )

    def update_message_file_thumbnail(
        self,
        message_id: str,
        file_index: int,
        thumbnail: str | None,
        status: ThumbnailStatus = ThumbnailStatus.READY,
    ) -> bool:
        """Update thumbnail for a specific file in a message.

        Used by background thumbnail generation to update the thumbnail
        after the message has been saved. The thumbnail is saved to the blob store
        and only the status is updated in the message metadata.

        Args:
            message_id: ID of the message
            file_index: Index of the file in the files array
            thumbnail: Base64-encoded thumbnail data (or None if generation failed)
            status: ThumbnailStatus.READY or ThumbnailStatus.FAILED

        Returns:
            True if updated successfully, False if message not found or index out of range
        """
        logger.debug(
            "Updating message file thumbnail",
            extra={"message_id": message_id, "file_index": file_index, "status": status.value},
        )

        with self._pool.get_connection() as conn:
            # Get current files JSON
            cursor = self._execute_with_timing(
                conn,
                "SELECT files FROM messages WHERE id = ?",
                (message_id,),
            )
            row = cursor.fetchone()

            if not row or not row["files"]:
                logger.warning(
                    "Message not found or has no files",
                    extra={"message_id": message_id, "file_index": file_index},
                )
                return False

            files = json.loads(row["files"])

            # Validate file index
            if file_index < 0 or file_index >= len(files):
                logger.warning(
                    "File index out of range",
                    extra={
                        "message_id": message_id,
                        "file_index": file_index,
                        "files_count": len(files),
                    },
                )
                return False

            # Save thumbnail to blob store if provided
            if thumbnail:
                try:
                    thumb_bytes = base64.b64decode(thumbnail)
                    blob_store = get_blob_store()
                    blob_store.save(
                        make_thumbnail_key(message_id, file_index), thumb_bytes, "image/jpeg"
                    )
                    files[file_index]["has_thumbnail"] = True
                except Exception:
                    logger.exception(
                        "Failed to save thumbnail to blob store",
                        extra={"message_id": message_id, "file_index": file_index},
                    )
                    status = ThumbnailStatus.FAILED
                    files[file_index]["has_thumbnail"] = False
            else:
                files[file_index]["has_thumbnail"] = False

            # Update status in metadata (no longer storing thumbnail in JSON)
            files[file_index]["thumbnail_status"] = status.value

            # Save back to database
            self._execute_with_timing(
                conn,
                "UPDATE messages SET files = ? WHERE id = ?",
                (json.dumps(files), message_id),
            )
            conn.commit()

            logger.debug(
                "Message file thumbnail updated",
                extra={"message_id": message_id, "file_index": file_index, "status": status.value},
            )
            return True
