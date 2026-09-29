"""Unit tests for the retrieve_file tool (src/agent/tools/file_retrieval.py)."""

import base64
import datetime as _dt
import json
from unittest.mock import MagicMock, patch

from src.agent.tools import (
    retrieve_file,
    set_conversation_context,
)

# ============================================================================
# Tests for File Retrieval Tool
# ============================================================================


class TestRetrieveFile:
    """Tests for retrieve_file tool."""

    def test_returns_error_without_context(self) -> None:
        """Should return error when no conversation context is set."""
        set_conversation_context(None, None)
        result = retrieve_file.invoke({"message_id": "msg-123"})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "No conversation context" in parsed["error"]

    @patch("src.db.models.db")
    def test_returns_error_for_unauthorized_conversation(self, mock_db: MagicMock) -> None:
        """Should return error when user doesn't own conversation."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = None

        result = retrieve_file.invoke({"message_id": "msg-123"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "not authorized" in parsed["error"]
        set_conversation_context(None, None)

    @patch("src.db.models.db")
    def test_returns_error_for_nonexistent_message(self, mock_db: MagicMock) -> None:
        """Should return error when message doesn't exist."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()
        mock_db.get_message_by_id.return_value = None

        result = retrieve_file.invoke({"message_id": "msg-999"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "Message not found" in parsed["error"]

        set_conversation_context(None, None)

    @patch("src.db.models.db")
    def test_returns_error_for_wrong_conversation(self, mock_db: MagicMock) -> None:
        """Should return error when message belongs to different conversation."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()

        mock_message = MagicMock()
        mock_message.conversation_id = "conv-different"
        mock_db.get_message_by_id.return_value = mock_message

        result = retrieve_file.invoke({"message_id": "msg-1"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "does not belong to this conversation" in parsed["error"]

        set_conversation_context(None, None)

    @patch("src.db.models.db")
    def test_returns_error_for_invalid_file_index(self, mock_db: MagicMock) -> None:
        """Should return error when file index is out of bounds."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()

        mock_message = MagicMock()
        mock_message.conversation_id = "conv-123"
        mock_message.files = [{"name": "only_one.jpg"}]
        mock_db.get_message_by_id.return_value = mock_message

        result = retrieve_file.invoke({"message_id": "msg-1", "file_index": 5})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "File index 5 not found" in parsed["error"]
        assert "has 1 file(s)" in parsed["error"]

        set_conversation_context(None, None)

    @patch("src.db.blob_store.get_blob_store")
    @patch("src.db.models.db")
    def test_retrieves_image_as_multimodal(
        self, mock_db: MagicMock, mock_get_blob_store: MagicMock
    ) -> None:
        """Should return image as multimodal content."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()

        mock_message = MagicMock()
        mock_message.conversation_id = "conv-123"
        mock_message.files = [{"name": "photo.jpg", "type": "image/jpeg", "size": 1000}]
        mock_message.created_at = _dt.datetime.now()
        mock_db.get_message_by_id.return_value = mock_message

        # Mock blob store
        mock_blob_store = MagicMock()
        mock_blob_store.get.return_value = (b"fake_image_data", "image/jpeg")
        mock_get_blob_store.return_value = mock_blob_store

        result = retrieve_file.invoke({"message_id": "msg-1", "file_index": 0})

        # Should return multimodal content
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["type"] == "text"
        assert "photo.jpg" in result[0]["text"]
        assert result[1]["type"] == "image"
        assert result[1]["mime_type"] == "image/jpeg"
        assert result[1]["base64"] == base64.b64encode(b"fake_image_data").decode("utf-8")

        set_conversation_context(None, None)

    @patch("src.db.blob_store.get_blob_store")
    @patch("src.db.models.db")
    def test_retrieves_text_file_as_text(
        self, mock_db: MagicMock, mock_get_blob_store: MagicMock
    ) -> None:
        """Should return text file content as plain text."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()

        mock_message = MagicMock()
        mock_message.conversation_id = "conv-123"
        mock_message.files = [{"name": "data.txt", "type": "text/plain", "size": 100}]
        mock_message.created_at = _dt.datetime.now()
        mock_db.get_message_by_id.return_value = mock_message

        # Mock blob store
        mock_blob_store = MagicMock()
        mock_blob_store.get.return_value = (b"Hello, world!", "text/plain")
        mock_get_blob_store.return_value = mock_blob_store

        result = retrieve_file.invoke({"message_id": "msg-1", "file_index": 0})

        # Should return text content as string
        assert isinstance(result, str)
        assert "Hello, world!" in result
        assert "data.txt" in result

        set_conversation_context(None, None)

    @patch("src.db.blob_store.get_blob_store")
    @patch("src.db.models.db")
    def test_falls_back_to_legacy_data(
        self, mock_db: MagicMock, mock_get_blob_store: MagicMock
    ) -> None:
        """Should fall back to legacy base64 data when blob store returns None."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()

        # Legacy data in message
        legacy_data = base64.b64encode(b"legacy_image_data").decode("utf-8")
        mock_message = MagicMock()
        mock_message.conversation_id = "conv-123"
        mock_message.files = [{"name": "old_photo.jpg", "type": "image/jpeg", "data": legacy_data}]
        mock_message.created_at = _dt.datetime.now()
        mock_db.get_message_by_id.return_value = mock_message

        # Blob store returns None
        mock_blob_store = MagicMock()
        mock_blob_store.get.return_value = None
        mock_get_blob_store.return_value = mock_blob_store

        result = retrieve_file.invoke({"message_id": "msg-1", "file_index": 0})

        assert isinstance(result, list)
        assert result[1]["base64"] == legacy_data

        set_conversation_context(None, None)

    @patch("src.db.blob_store.get_blob_store")
    @patch("src.db.models.db")
    def test_returns_error_when_no_data_available(
        self, mock_db: MagicMock, mock_get_blob_store: MagicMock
    ) -> None:
        """Should return error when neither blob store nor legacy data is available."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()

        mock_message = MagicMock()
        mock_message.conversation_id = "conv-123"
        mock_message.files = [
            {"name": "missing.jpg", "type": "image/jpeg"}  # No "data" key
        ]
        mock_message.created_at = _dt.datetime.now()
        mock_db.get_message_by_id.return_value = mock_message

        # Blob store returns None
        mock_blob_store = MagicMock()
        mock_blob_store.get.return_value = None
        mock_get_blob_store.return_value = mock_blob_store

        result = retrieve_file.invoke({"message_id": "msg-1", "file_index": 0})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "not found in storage" in parsed["error"]

        set_conversation_context(None, None)


class TestRetrieveFileVideo:
    """Tests for retrieve_file video support and retention expiry."""

    @staticmethod
    def _video_message(days_old: int = 0, mime: str = "video/mp4", name: str = "clip.mp4"):
        from datetime import datetime, timedelta

        mock_message = MagicMock()
        mock_message.conversation_id = "conv-123"
        mock_message.files = [{"name": name, "type": mime, "size": 1000}]
        mock_message.created_at = datetime.now() - timedelta(days=days_old)
        return mock_message

    @patch("src.agent.gemini_files.ensure_gemini_file_uri")
    @patch("src.db.blob_store.get_blob_store")
    @patch("src.db.models.db")
    def test_video_returns_media_block(
        self,
        mock_db: MagicMock,
        mock_get_blob_store: MagicMock,
        mock_ensure: MagicMock,
    ) -> None:
        """Should return video as a Files API media block."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()
        mock_db.get_message_by_id.return_value = self._video_message()

        mock_blob_store = MagicMock()
        mock_blob_store.get.return_value = (b"fake_video_data", "video/mp4")
        mock_get_blob_store.return_value = mock_blob_store
        mock_ensure.return_value = "https://files.example/f1"

        result = retrieve_file.invoke({"message_id": "msg-1", "file_index": 0})

        assert isinstance(result, list)
        assert result[0]["type"] == "text"
        assert "clip.mp4" in result[0]["text"]
        assert result[1] == {
            "type": "media",
            "file_uri": "https://files.example/f1",
            "mime_type": "video/mp4",
        }
        mock_ensure.assert_called_once_with("msg-1", 0, b"fake_video_data", "video/mp4")

        set_conversation_context(None, None)

    @patch("src.db.models.db")
    def test_expired_video_returns_cleanup_error(self, mock_db: MagicMock) -> None:
        """Should return a clear cleanup error for videos past retention."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()
        mock_db.get_message_by_id.return_value = self._video_message(days_old=8)

        result = retrieve_file.invoke({"message_id": "msg-1", "file_index": 0})
        parsed = json.loads(result)

        assert "cleaned up" in parsed["error"]
        assert "7 days" in parsed["error"]

        set_conversation_context(None, None)

    @patch("src.db.models.db")
    def test_expired_image_returns_cleanup_error(self, mock_db: MagicMock) -> None:
        """Should return a clear cleanup error for images past retention."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()
        mock_db.get_message_by_id.return_value = self._video_message(
            days_old=31, mime="image/png", name="old.png"
        )

        result = retrieve_file.invoke({"message_id": "msg-1", "file_index": 0})
        parsed = json.loads(result)

        assert "cleaned up" in parsed["error"]
        assert "30 days" in parsed["error"]

        set_conversation_context(None, None)

    @patch("src.agent.gemini_files.ensure_gemini_file_uri")
    @patch("src.db.blob_store.get_blob_store")
    @patch("src.db.models.db")
    def test_gemini_failure_returns_error(
        self,
        mock_db: MagicMock,
        mock_get_blob_store: MagicMock,
        mock_ensure: MagicMock,
    ) -> None:
        """Should return an error JSON when the Files API upload fails."""
        from src.agent.gemini_files import GeminiFileError

        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()
        mock_db.get_message_by_id.return_value = self._video_message()

        mock_blob_store = MagicMock()
        mock_blob_store.get.return_value = (b"fake_video_data", "video/mp4")
        mock_get_blob_store.return_value = mock_blob_store
        mock_ensure.side_effect = GeminiFileError("quota exceeded")

        result = retrieve_file.invoke({"message_id": "msg-1", "file_index": 0})
        parsed = json.loads(result)

        assert "quota exceeded" in parsed["error"]

        set_conversation_context(None, None)
