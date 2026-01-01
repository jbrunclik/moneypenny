"""Integration tests for thumbnail routes with background generation."""

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch

from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, User


class TestGetMessageThumbnail:
    """Tests for GET /api/messages/<id>/files/<idx>/thumbnail endpoint."""

    def test_returns_200_when_thumbnail_ready(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_conversation: Conversation,
        test_database: Database,
        sample_png_base64: str,
    ) -> None:
        """Should return 200 with thumbnail data when status is ready."""
        # Create a message with a ready thumbnail
        # Note: thumbnails are stored as image/jpeg regardless of original image type
        files = [
            {
                "name": "test.png",
                "type": "image/png",
                "data": sample_png_base64,
                "thumbnail": sample_png_base64,
                "thumbnail_status": "ready",
            }
        ]
        message = test_database.add_message(
            test_conversation.id, "user", "Test message", files=files
        )

        response = client.get(
            f"/api/messages/{message.id}/files/0/thumbnail",
            headers=auth_headers,
        )

        assert response.status_code == 200
        # Thumbnails are always stored and returned as JPEG in blob store
        assert response.content_type == "image/jpeg"

    def test_returns_202_when_thumbnail_pending(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_conversation: Conversation,
        test_database: Database,
        sample_png_base64: str,
    ) -> None:
        """Should return 202 with pending status when thumbnail is being generated."""
        # Create a message with a pending thumbnail
        files = [
            {
                "name": "test.png",
                "type": "image/png",
                "data": sample_png_base64,
                "thumbnail_status": "pending",
            }
        ]
        message = test_database.add_message(
            test_conversation.id, "user", "Test message", files=files
        )

        response = client.get(
            f"/api/messages/{message.id}/files/0/thumbnail",
            headers=auth_headers,
        )

        assert response.status_code == 202
        data = json.loads(response.data)
        assert data["status"] == "pending"

    def test_falls_back_to_full_image_when_failed(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_conversation: Conversation,
        test_database: Database,
        sample_png_base64: str,
    ) -> None:
        """Should return full image when thumbnail generation failed."""
        # Create a message with a failed thumbnail
        files = [
            {
                "name": "test.png",
                "type": "image/png",
                "data": sample_png_base64,
                "thumbnail_status": "failed",
            }
        ]
        message = test_database.add_message(
            test_conversation.id, "user", "Test message", files=files
        )

        response = client.get(
            f"/api/messages/{message.id}/files/0/thumbnail",
            headers=auth_headers,
        )

        # Should fall back to full image
        assert response.status_code == 200
        assert response.content_type == "image/png"

    def test_regenerates_stale_pending_thumbnail(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_conversation: Conversation,
        test_database: Database,
        sample_png_base64: str,
    ) -> None:
        """Should regenerate thumbnail if pending for too long (server death recovery)."""
        from src.config import Config

        # Create a message with a pending thumbnail
        files = [
            {
                "name": "test.png",
                "type": "image/png",
                "data": sample_png_base64,
                "thumbnail_status": "pending",
            }
        ]
        message = test_database.add_message(
            test_conversation.id, "user", "Test message", files=files
        )

        # Manually set the message created_at to be older than the threshold
        stale_time = datetime.now() - timedelta(
            seconds=Config.THUMBNAIL_STALE_THRESHOLD_SECONDS + 10
        )
        with test_database._get_conn() as conn:
            conn.execute(
                "UPDATE messages SET created_at = ? WHERE id = ?",
                (stale_time.isoformat(), message.id),
            )
            conn.commit()

        # Mock generate_thumbnail to verify it's called (via generate_and_save_thumbnail)
        with patch(
            "src.utils.images.generate_thumbnail", return_value=sample_png_base64
        ) as mock_gen:
            response = client.get(
                f"/api/messages/{message.id}/files/0/thumbnail",
                headers=auth_headers,
            )

            # Should regenerate and return 200
            assert response.status_code == 200
            mock_gen.assert_called_once()

        # Verify the database was updated
        updated_message = test_database.get_message_by_id(message.id)
        assert updated_message is not None
        assert updated_message.files[0]["thumbnail_status"] == "ready"

    def test_handles_legacy_messages_without_status(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_conversation: Conversation,
        test_database: Database,
        sample_png_base64: str,
    ) -> None:
        """Should handle legacy messages without thumbnail_status field."""
        # Create a message without thumbnail_status (legacy format)
        # Note: thumbnails are stored as image/jpeg regardless of original image type
        files = [
            {
                "name": "test.png",
                "type": "image/png",
                "data": sample_png_base64,
                "thumbnail": sample_png_base64,
                # No thumbnail_status field
            }
        ]
        message = test_database.add_message(
            test_conversation.id, "user", "Test message", files=files
        )

        response = client.get(
            f"/api/messages/{message.id}/files/0/thumbnail",
            headers=auth_headers,
        )

        # Should return thumbnail (defaults to "ready" status)
        # Thumbnails are always stored and returned as JPEG in blob store
        assert response.status_code == 200
        assert response.content_type == "image/jpeg"

    def test_returns_404_for_nonexistent_message(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 404 for nonexistent message."""
        response = client.get(
            "/api/messages/nonexistent-id/files/0/thumbnail",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_returns_404_for_invalid_file_index(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_conversation: Conversation,
        test_database: Database,
        sample_png_base64: str,
    ) -> None:
        """Should return 404 for invalid file index."""
        files = [
            {
                "name": "test.png",
                "type": "image/png",
                "data": sample_png_base64,
                "thumbnail_status": "ready",
            }
        ]
        message = test_database.add_message(
            test_conversation.id, "user", "Test message", files=files
        )

        response = client.get(
            f"/api/messages/{message.id}/files/99/thumbnail",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/messages/some-id/files/0/thumbnail")
        assert response.status_code == 401


class TestUpdateMessageFileThumbnail:
    """Tests for Database.update_message_file_thumbnail method."""

    def test_updates_thumbnail(
        self,
        test_database: Database,
        test_conversation: Conversation,
        test_blob_store,
        sample_png_base64: str,
    ) -> None:
        """Should update thumbnail for a specific file."""
        import base64

        from src.db.models import make_thumbnail_key

        # Create a message with pending thumbnail
        files = [
            {
                "name": "test.png",
                "type": "image/png",
                "data": sample_png_base64,
                "thumbnail_status": "pending",
            }
        ]
        message = test_database.add_message(
            test_conversation.id, "user", "Test message", files=files
        )

        # Create valid base64 thumbnail data
        thumb_data = b"thumbnail binary data"
        thumb_base64 = base64.b64encode(thumb_data).decode()

        # Update the thumbnail
        success = test_database.update_message_file_thumbnail(
            message.id, 0, thumb_base64, status="ready"
        )

        assert success is True

        # Verify the metadata update
        updated = test_database.get_message_by_id(message.id)
        assert updated is not None
        assert updated.files[0]["has_thumbnail"] is True
        assert updated.files[0]["thumbnail_status"] == "ready"
        # Thumbnail data should NOT be in the JSON (stored in blob store)
        assert "thumbnail" not in updated.files[0]

        # Verify thumbnail is in blob store
        thumb_key = make_thumbnail_key(message.id, 0)
        result = test_blob_store.get(thumb_key)
        assert result is not None
        data, mime_type = result
        assert data == thumb_data
        assert mime_type == "image/jpeg"

    def test_updates_correct_file_in_multi_file_message(
        self,
        test_database: Database,
        test_conversation: Conversation,
        test_blob_store,
        sample_png_base64: str,
    ) -> None:
        """Should update only the specified file in a multi-file message."""
        import base64

        from src.db.models import make_thumbnail_key

        # Create a message with multiple files
        files = [
            {
                "name": "test1.png",
                "type": "image/png",
                "data": sample_png_base64,
                "thumbnail_status": "pending",
            },
            {
                "name": "test2.png",
                "type": "image/png",
                "data": sample_png_base64,
                "thumbnail_status": "pending",
            },
        ]
        message = test_database.add_message(
            test_conversation.id, "user", "Test message", files=files
        )

        # Create valid base64 thumbnail data
        thumb_data = b"thumbnail for file 2"
        thumb_base64 = base64.b64encode(thumb_data).decode()

        # Update only the second file
        success = test_database.update_message_file_thumbnail(
            message.id, 1, thumb_base64, status="ready"
        )

        assert success is True

        # Verify only the second file was updated in metadata
        updated = test_database.get_message_by_id(message.id)
        assert updated is not None
        assert updated.files[0]["thumbnail_status"] == "pending"
        assert updated.files[0].get("has_thumbnail") is False
        assert updated.files[1]["thumbnail_status"] == "ready"
        assert updated.files[1]["has_thumbnail"] is True
        # Thumbnail data should NOT be in the JSON (stored in blob store)
        assert "thumbnail" not in updated.files[1]

        # Verify only second file's thumbnail is in blob store
        thumb_key_0 = make_thumbnail_key(message.id, 0)
        thumb_key_1 = make_thumbnail_key(message.id, 1)
        assert test_blob_store.get(thumb_key_0) is None  # First file has no thumbnail
        result = test_blob_store.get(thumb_key_1)
        assert result is not None
        data, mime_type = result
        assert data == thumb_data
        assert mime_type == "image/jpeg"

    def test_returns_false_for_nonexistent_message(
        self,
        test_database: Database,
    ) -> None:
        """Should return False for nonexistent message."""
        success = test_database.update_message_file_thumbnail(
            "nonexistent-id", 0, "thumbnail", status="ready"
        )

        assert success is False

    def test_returns_false_for_invalid_file_index(
        self,
        test_database: Database,
        test_conversation: Conversation,
        sample_png_base64: str,
    ) -> None:
        """Should return False for invalid file index."""
        files = [
            {
                "name": "test.png",
                "type": "image/png",
                "data": sample_png_base64,
                "thumbnail_status": "pending",
            }
        ]
        message = test_database.add_message(
            test_conversation.id, "user", "Test message", files=files
        )

        # Try to update index that doesn't exist
        success = test_database.update_message_file_thumbnail(
            message.id, 99, "thumbnail", status="ready"
        )

        assert success is False

    def test_returns_false_for_message_without_files(
        self,
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        """Should return False for message without files."""
        message = test_database.add_message(test_conversation.id, "user", "No files message")

        success = test_database.update_message_file_thumbnail(
            message.id, 0, "thumbnail", status="ready"
        )

        assert success is False
