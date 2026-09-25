"""Tests for retrieve_file size handling (Gemini's ~20 MB inline request limit)."""

import base64
import datetime as _dt
import io
import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.agent.tools import retrieve_file
from src.agent.tools.context import set_conversation_context
from src.config import Config


@pytest.fixture(autouse=True)
def _conversation_context() -> Iterator[None]:
    set_conversation_context("conv-123", "user-456")
    yield
    set_conversation_context(None, None)


def _jpeg(width: int, height: int) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color="blue").save(output, format="JPEG")
    return output.getvalue()


def _retrieve(
    mock_db: MagicMock,
    mock_get_blob_store: MagicMock,
    data: bytes,
    mime_type: str,
    name: str = "file",
) -> Any:
    mock_db.get_conversation.return_value = MagicMock()
    message = MagicMock()
    message.conversation_id = "conv-123"
    message.files = [{"name": name, "type": mime_type, "size": len(data)}]
    message.created_at = _dt.datetime.now()
    mock_db.get_message_by_id.return_value = message
    blob_store = MagicMock()
    blob_store.get.return_value = (data, mime_type)
    mock_get_blob_store.return_value = blob_store
    return retrieve_file.invoke({"message_id": "msg-1", "file_index": 0})


@patch("src.db.blob_store.get_blob_store")
@patch("src.db.models.db")
class TestRetrieveFileLimits:
    def test_large_image_is_downscaled_inline(
        self, mock_db: MagicMock, mock_get_blob_store: MagicMock
    ) -> None:
        result = _retrieve(mock_db, mock_get_blob_store, _jpeg(4096, 4096), "image/jpeg")

        assert result[1]["type"] == "image"
        sent = Image.open(io.BytesIO(base64.b64decode(result[1]["base64"])))
        assert max(sent.size) == Config.IMAGE_REFERENCE_MAX_EDGE_PX

    @patch("src.agent.gemini_files.ensure_gemini_file_uri")
    def test_large_pdf_goes_through_files_api(
        self,
        mock_ensure: MagicMock,
        mock_db: MagicMock,
        mock_get_blob_store: MagicMock,
    ) -> None:
        mock_ensure.return_value = "https://files.example/pdf1"
        data = b"%PDF-" + b"x" * 2000
        with patch.object(Config, "GEMINI_INLINE_FILE_MAX_BYTES", 1000):
            result = _retrieve(mock_db, mock_get_blob_store, data, "application/pdf", "doc.pdf")

        assert result[1] == {
            "type": "media",
            "file_uri": "https://files.example/pdf1",
            "mime_type": "application/pdf",
        }
        mock_ensure.assert_called_once_with("msg-1", 0, data, "application/pdf")

    @patch("src.agent.gemini_files.ensure_gemini_file_uri")
    def test_small_pdf_stays_inline(
        self,
        mock_ensure: MagicMock,
        mock_db: MagicMock,
        mock_get_blob_store: MagicMock,
    ) -> None:
        data = b"%PDF-small"
        result = _retrieve(mock_db, mock_get_blob_store, data, "application/pdf", "doc.pdf")

        assert result[1]["type"] == "image"
        assert result[1]["base64"] == base64.b64encode(data).decode("utf-8")
        mock_ensure.assert_not_called()

    @patch("src.agent.gemini_files.ensure_gemini_file_uri")
    def test_files_api_failure_returns_error(
        self,
        mock_ensure: MagicMock,
        mock_db: MagicMock,
        mock_get_blob_store: MagicMock,
    ) -> None:
        from src.agent.gemini_files import GeminiFileError

        mock_ensure.side_effect = GeminiFileError("quota exceeded")
        with patch.object(Config, "GEMINI_INLINE_FILE_MAX_BYTES", 10):
            result = _retrieve(mock_db, mock_get_blob_store, b"%PDF-" * 10, "application/pdf")

        assert "quota exceeded" in json.loads(result)["error"]

    def test_long_text_file_is_truncated(
        self, mock_db: MagicMock, mock_get_blob_store: MagicMock
    ) -> None:
        with patch.object(Config, "RETRIEVE_FILE_TEXT_MAX_CHARS", 100):
            result = _retrieve(mock_db, mock_get_blob_store, b"a" * 500, "text/plain", "big.txt")

        assert "a" * 100 in result
        assert "a" * 101 not in result
        assert "truncated" in result
        assert "500" in result  # total length reported

    def test_binary_file_returns_metadata_without_data(
        self, mock_db: MagicMock, mock_get_blob_store: MagicMock
    ) -> None:
        result = _retrieve(
            mock_db, mock_get_blob_store, b"\x00\x01" * 1000, "application/octet-stream", "b.bin"
        )
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["file"]["name"] == "b.bin"
        assert parsed["file"]["size"] == 2000
        assert "data" not in parsed["file"]
