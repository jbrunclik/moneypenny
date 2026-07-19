"""Tests for the Gemini Files API bridge."""

import base64
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.agent import gemini_files
from src.agent.gemini_files import (
    GEMINI_FILES_NAMESPACE,
    SYSTEM_KV_USER_ID,
    GeminiFileError,
    attach_gemini_file_uris,
    ensure_gemini_file_uri,
)


@pytest.fixture(autouse=True)
def _use_test_db(test_database, monkeypatch):
    """Point the module's db reference at the isolated test database."""
    monkeypatch.setattr(gemini_files, "db", test_database)
    yield


def _mock_client(state_sequence=("ACTIVE",), uri="https://files.example/f1"):
    """Build a genai client mock whose files.get walks state_sequence."""
    client = MagicMock()
    uploaded = SimpleNamespace(
        name="files/f1", uri=uri, state=SimpleNamespace(name=state_sequence[0])
    )
    client.files.upload.return_value = uploaded
    states = [
        SimpleNamespace(name="files/f1", uri=uri, state=SimpleNamespace(name=s))
        for s in state_sequence[1:]
    ]
    client.files.get.side_effect = states
    return client


class TestEnsureGeminiFileUri:
    def test_uploads_and_caches(self, test_database) -> None:
        client = _mock_client(("ACTIVE",))
        with patch("src.agent.gemini_files._get_client", return_value=client):
            uri = ensure_gemini_file_uri("msg-1", 0, b"vid", "video/mp4")
        assert uri == "https://files.example/f1"
        cached = test_database.kv_get(SYSTEM_KV_USER_ID, GEMINI_FILES_NAMESPACE, "msg-1:0")
        assert cached is not None
        assert json.loads(cached)["uri"] == uri

    def test_cache_hit_skips_upload(self) -> None:
        client = _mock_client(("ACTIVE",))
        with patch("src.agent.gemini_files._get_client", return_value=client):
            ensure_gemini_file_uri("msg-2", 0, b"vid", "video/mp4")
            ensure_gemini_file_uri("msg-2", 0, b"vid", "video/mp4")
        assert client.files.upload.call_count == 1

    def test_expired_cache_reuploads(self, test_database) -> None:
        test_database.kv_set(
            SYSTEM_KV_USER_ID,
            GEMINI_FILES_NAMESPACE,
            "msg-old:0",
            json.dumps(
                {
                    "uri": "https://files.example/stale",
                    "name": "files/stale",
                    "expires_at": "2020-01-01T00:00:00",
                }
            ),
        )
        client = _mock_client(("ACTIVE",))
        with patch("src.agent.gemini_files._get_client", return_value=client):
            uri = ensure_gemini_file_uri("msg-old", 0, b"vid", "video/mp4")
        assert uri == "https://files.example/f1"
        assert client.files.upload.call_count == 1

    def test_polls_until_active(self) -> None:
        client = _mock_client(("PROCESSING", "ACTIVE"))
        with (
            patch("src.agent.gemini_files._get_client", return_value=client),
            patch("src.agent.gemini_files.time.sleep"),
        ):
            uri = ensure_gemini_file_uri("msg-3", 0, b"vid", "video/mp4")
        assert uri == "https://files.example/f1"

    def test_failed_processing_raises(self) -> None:
        client = _mock_client(("PROCESSING", "FAILED"))
        with (
            patch("src.agent.gemini_files._get_client", return_value=client),
            patch("src.agent.gemini_files.time.sleep"),
            pytest.raises(GeminiFileError),
        ):
            ensure_gemini_file_uri("msg-4", 0, b"vid", "video/mp4")

    def test_upload_exception_wrapped(self) -> None:
        client = MagicMock()
        client.files.upload.side_effect = RuntimeError("network down")
        with (
            patch("src.agent.gemini_files._get_client", return_value=client),
            pytest.raises(GeminiFileError, match="network down"),
        ):
            ensure_gemini_file_uri("msg-5", 0, b"vid", "video/mp4")


class TestAttachGeminiFileUris:
    def test_attaches_uri_to_videos_only(self) -> None:
        client = _mock_client(("ACTIVE",))
        files = [
            {"name": "a.png", "type": "image/png", "data": base64.b64encode(b"x").decode()},
            {"name": "b.mp4", "type": "video/mp4", "data": base64.b64encode(b"v").decode()},
        ]
        with patch("src.agent.gemini_files._get_client", return_value=client):
            attach_gemini_file_uris("msg-6", files)
        assert "gemini_file_uri" not in files[0]
        assert files[1]["gemini_file_uri"] == "https://files.example/f1"

    def test_upload_failure_sets_error_not_exception(self) -> None:
        client = _mock_client(("PROCESSING", "FAILED"))
        files = [{"name": "b.mp4", "type": "video/mp4", "data": base64.b64encode(b"v").decode()}]
        with (
            patch("src.agent.gemini_files._get_client", return_value=client),
            patch("src.agent.gemini_files.time.sleep"),
        ):
            attach_gemini_file_uris("msg-7", files)
        assert "gemini_file_uri" not in files[0]
        assert "gemini_upload_error" in files[0]


class TestDeleteCachedFileUri:
    def test_deletes_cache_entry(self, test_database) -> None:
        test_database.kv_set(SYSTEM_KV_USER_ID, GEMINI_FILES_NAMESPACE, "msg-8:0", '{"uri": "x"}')
        gemini_files.delete_cached_file_uri("msg-8", 0)
        assert test_database.kv_get(SYSTEM_KV_USER_ID, GEMINI_FILES_NAMESPACE, "msg-8:0") is None
