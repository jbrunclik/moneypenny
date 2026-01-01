"""
Migrate existing file data from chatbot.db to blob store (files.db).

This migration:
1. Reads all messages with file attachments
2. Extracts base64 data and thumbnails from the JSON
3. Saves them to the blob store
4. Updates the message JSON to remove data/thumbnail and add size/has_thumbnail

The migration is idempotent - it skips files that already exist in the blob store.
"""

import base64
import json

from yoyo import step

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


def migrate_files_to_blob_store(conn):
    """Migrate file data from messages JSON to blob store."""
    # Import here to avoid circular imports during migration
    from src.db.blob_store import BlobStore

    blob_store = BlobStore(Config.BLOB_STORAGE_PATH)

    # Count messages to migrate
    cursor = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE files IS NOT NULL AND files != '[]'"
    )
    total_messages = cursor.fetchone()[0]
    print(f"Found {total_messages} messages with files to migrate")

    if total_messages == 0:
        print("No files to migrate")
        return

    # Process messages in batches
    batch_size = 100
    offset = 0
    migrated_files = 0
    migrated_thumbnails = 0
    skipped_files = 0

    while offset < total_messages:
        cursor = conn.execute(
            """
            SELECT id, files FROM messages
            WHERE files IS NOT NULL AND files != '[]'
            ORDER BY created_at
            LIMIT ? OFFSET ?
            """,
            (batch_size, offset),
        )
        rows = cursor.fetchall()

        if not rows:
            break

        for row in rows:
            message_id = row[0]
            files_json = row[1]

            try:
                files = json.loads(files_json)
            except json.JSONDecodeError:
                print(f"  Warning: Invalid JSON in message {message_id}, skipping")
                continue

            updated = False
            for idx, file in enumerate(files):
                blob_key = f"{message_id}/{idx}"
                thumb_key = f"{message_id}/{idx}.thumb"

                # Migrate main file data
                file_data = file.get("data")
                if file_data:
                    # Check if already migrated
                    if not blob_store.exists(blob_key):
                        try:
                            data_bytes = base64.b64decode(file_data)
                            mime_type = file.get("type", "application/octet-stream")
                            blob_store.save(blob_key, data_bytes, mime_type)
                            migrated_files += 1

                            # Update metadata
                            file["size"] = len(data_bytes)
                        except Exception as e:
                            print(f"  Warning: Failed to migrate file {blob_key}: {e}")
                            continue
                    else:
                        skipped_files += 1
                        # Still need to add size if missing
                        if "size" not in file:
                            try:
                                file["size"] = len(base64.b64decode(file_data))
                            except Exception:
                                file["size"] = 0

                    # Remove data from JSON
                    del file["data"]
                    updated = True

                # Migrate thumbnail
                thumbnail_data = file.get("thumbnail")
                if thumbnail_data:
                    # Check if already migrated
                    if not blob_store.exists(thumb_key):
                        try:
                            thumb_bytes = base64.b64decode(thumbnail_data)
                            blob_store.save(thumb_key, thumb_bytes, "image/jpeg")
                            migrated_thumbnails += 1
                        except Exception as e:
                            print(f"  Warning: Failed to migrate thumbnail {thumb_key}: {e}")

                    # Update metadata
                    file["has_thumbnail"] = True
                    del file["thumbnail"]
                    updated = True
                elif file.get("thumbnail_status") == "ready":
                    # Had thumbnail_status=ready but no thumbnail data
                    # This shouldn't happen but handle it gracefully
                    file["has_thumbnail"] = False

            # Update the message with cleaned metadata
            if updated:
                conn.execute(
                    "UPDATE messages SET files = ? WHERE id = ?",
                    (json.dumps(files), message_id),
                )

        conn.commit()
        offset += batch_size
        print(f"  Processed {min(offset, total_messages)}/{total_messages} messages...")

    print(f"Migration complete:")
    print(f"  - Migrated {migrated_files} files")
    print(f"  - Migrated {migrated_thumbnails} thumbnails")
    print(f"  - Skipped {skipped_files} files (already in blob store)")


def rollback_migration(conn):
    """Rollback: Restore file data from blob store to messages JSON.

    Note: This is a best-effort rollback. If files were deleted from the
    blob store, they cannot be restored.
    """
    from src.db.blob_store import BlobStore

    blob_store = BlobStore(Config.BLOB_STORAGE_PATH)

    cursor = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE files IS NOT NULL AND files != '[]'"
    )
    total_messages = cursor.fetchone()[0]
    print(f"Rolling back {total_messages} messages...")

    if total_messages == 0:
        return

    batch_size = 100
    offset = 0
    restored_files = 0

    while offset < total_messages:
        cursor = conn.execute(
            """
            SELECT id, files FROM messages
            WHERE files IS NOT NULL AND files != '[]'
            ORDER BY created_at
            LIMIT ? OFFSET ?
            """,
            (batch_size, offset),
        )
        rows = cursor.fetchall()

        if not rows:
            break

        for row in rows:
            message_id = row[0]
            files_json = row[1]

            try:
                files = json.loads(files_json)
            except json.JSONDecodeError:
                continue

            updated = False
            for idx, file in enumerate(files):
                blob_key = f"{message_id}/{idx}"
                thumb_key = f"{message_id}/{idx}.thumb"

                # Restore main file data
                if "data" not in file:
                    result = blob_store.get(blob_key)
                    if result:
                        data_bytes, _ = result
                        file["data"] = base64.b64encode(data_bytes).decode("utf-8")
                        restored_files += 1
                        updated = True

                # Restore thumbnail
                if file.get("has_thumbnail") and "thumbnail" not in file:
                    result = blob_store.get(thumb_key)
                    if result:
                        thumb_bytes, _ = result
                        file["thumbnail"] = base64.b64encode(thumb_bytes).decode("utf-8")
                        updated = True

                # Remove new metadata fields
                file.pop("has_thumbnail", None)
                file.pop("size", None)

            if updated:
                conn.execute(
                    "UPDATE messages SET files = ? WHERE id = ?",
                    (json.dumps(files), message_id),
                )

        conn.commit()
        offset += batch_size

    print(f"Rollback complete: restored {restored_files} files")


steps = [
    step(migrate_files_to_blob_store, rollback_migration),
]
