"""Message file database operations mixin (thumbnails, retention sweep)."""

from __future__ import annotations

import base64
import json
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.api.schemas.common import ThumbnailStatus
from src.db.blob_store import get_blob_store
from src.db.models.dataclasses import Message
from src.db.models.helpers import make_thumbnail_key
from src.db.models.message_rows import row_to_message
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class MessageFileMixin:
    """Mixin providing message file-attachment operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def get_messages_with_files_before(self, cutoff: datetime) -> list[Message]:
        """Messages older than cutoff that have file attachments (for retention sweep)."""
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """SELECT * FROM messages
                   WHERE files IS NOT NULL AND files != '[]' AND created_at < ?
                   ORDER BY created_at""",
                (cutoff.isoformat(),),
            ).fetchall()
            return [row_to_message(row) for row in rows]

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

            # Atomic single-statement update of ONLY this file's fields:
            # writing back the whole files JSON lost concurrent updates when
            # two thumbnail workers processed a multi-image message (R5)
            has_thumbnail = bool(files[file_index].get("has_thumbnail"))
            idx = int(file_index)
            self._execute_with_timing(
                conn,
                f"""UPDATE messages
                   SET files = json_set(
                       files,
                       '$[{idx}].has_thumbnail', json(?),
                       '$[{idx}].thumbnail_status', ?
                   )
                   WHERE id = ?""",
                ("true" if has_thumbnail else "false", status.value, message_id),
            )
            conn.commit()

            logger.debug(
                "Message file thumbnail updated",
                extra={"message_id": message_id, "file_index": file_index, "status": status.value},
            )
            return True
