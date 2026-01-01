"""Unit tests for blob store."""

import tempfile
from pathlib import Path

import pytest

from src.db.blob_store import BlobStore


class TestBlobStore:
    """Test blob store operations."""

    @pytest.fixture
    def blob_store(self):
        """Create a blob store with a temporary database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_blobs.db"
            yield BlobStore(db_path)

    def test_save_and_get(self, blob_store):
        """Test basic save and retrieve."""
        key = "msg-123/0"
        data = b"hello world"
        mime_type = "text/plain"

        blob_store.save(key, data, mime_type)

        result = blob_store.get(key)
        assert result is not None
        retrieved_data, retrieved_mime = result
        assert retrieved_data == data
        assert retrieved_mime == mime_type

    def test_get_nonexistent(self, blob_store):
        """Test getting a key that doesn't exist."""
        result = blob_store.get("nonexistent")
        assert result is None

    def test_exists(self, blob_store):
        """Test exists check."""
        key = "msg-123/0"

        assert not blob_store.exists(key)

        blob_store.save(key, b"data", "text/plain")

        assert blob_store.exists(key)

    def test_delete(self, blob_store):
        """Test deleting a blob."""
        key = "msg-123/0"
        blob_store.save(key, b"data", "text/plain")

        assert blob_store.exists(key)

        result = blob_store.delete(key)
        assert result is True

        assert not blob_store.exists(key)

    def test_delete_nonexistent(self, blob_store):
        """Test deleting a nonexistent key."""
        result = blob_store.delete("nonexistent")
        assert result is False

    def test_delete_by_prefix(self, blob_store):
        """Test deleting all blobs with a prefix."""
        # Create several blobs for the same message
        blob_store.save("msg-123/0", b"file0", "text/plain")
        blob_store.save("msg-123/0.thumb", b"thumb0", "image/jpeg")
        blob_store.save("msg-123/1", b"file1", "text/plain")
        blob_store.save("msg-456/0", b"other", "text/plain")

        # Delete all for msg-123
        count = blob_store.delete_by_prefix("msg-123/")

        assert count == 3
        assert not blob_store.exists("msg-123/0")
        assert not blob_store.exists("msg-123/0.thumb")
        assert not blob_store.exists("msg-123/1")
        # Other message should still exist
        assert blob_store.exists("msg-456/0")

    def test_get_size(self, blob_store):
        """Test getting blob size without loading data."""
        key = "msg-123/0"
        data = b"hello world"

        blob_store.save(key, data, "text/plain")

        size = blob_store.get_size(key)
        assert size == len(data)

    def test_get_size_nonexistent(self, blob_store):
        """Test getting size of nonexistent blob."""
        size = blob_store.get_size("nonexistent")
        assert size is None

    def test_save_replaces_existing(self, blob_store):
        """Test that save replaces existing data."""
        key = "msg-123/0"

        blob_store.save(key, b"original", "text/plain")
        blob_store.save(key, b"updated", "application/json")

        result = blob_store.get(key)
        assert result is not None
        data, mime = result
        assert data == b"updated"
        assert mime == "application/json"

    def test_large_blob(self, blob_store):
        """Test storing and retrieving large data."""
        key = "msg-123/0"
        # 1 MB of data
        data = b"x" * (1024 * 1024)

        blob_store.save(key, data, "application/octet-stream")

        result = blob_store.get(key)
        assert result is not None
        retrieved_data, _ = result
        assert len(retrieved_data) == len(data)
        assert retrieved_data == data

    def test_binary_data(self, blob_store):
        """Test storing binary data with null bytes."""
        key = "msg-123/0"
        # Binary data with various byte values including null
        data = bytes(range(256))

        blob_store.save(key, data, "application/octet-stream")

        result = blob_store.get(key)
        assert result is not None
        retrieved_data, _ = result
        assert retrieved_data == data


class TestBlobStoreKeyFormat:
    """Test key format helpers."""

    def test_make_blob_key(self):
        """Test blob key generation."""
        from src.db.models import make_blob_key

        key = make_blob_key("msg-123", 0)
        assert key == "msg-123/0"

        key = make_blob_key("abc-def-456", 2)
        assert key == "abc-def-456/2"

    def test_make_thumbnail_key(self):
        """Test thumbnail key generation."""
        from src.db.models import make_thumbnail_key

        key = make_thumbnail_key("msg-123", 0)
        assert key == "msg-123/0.thumb"

        key = make_thumbnail_key("abc-def-456", 2)
        assert key == "abc-def-456/2.thumb"


class TestExtractFileMetadata:
    """Test file metadata extraction."""

    def test_extract_basic_metadata(self):
        """Test extracting metadata from file dict."""
        from src.db.models import extract_file_metadata

        file_data = {
            "name": "photo.jpg",
            "type": "image/jpeg",
            "data": "aGVsbG8gd29ybGQ=",  # "hello world" in base64
        }

        metadata = extract_file_metadata(file_data)

        assert metadata["name"] == "photo.jpg"
        assert metadata["type"] == "image/jpeg"
        assert metadata["size"] == 11  # len("hello world")
        assert "data" not in metadata
        assert metadata["has_thumbnail"] is False

    def test_extract_with_thumbnail(self):
        """Test extracting metadata when thumbnail present."""
        from src.db.models import extract_file_metadata

        file_data = {
            "name": "photo.jpg",
            "type": "image/jpeg",
            "data": "aGVsbG8gd29ybGQ=",
            "thumbnail": "dGh1bWJuYWls",
            "thumbnail_status": "ready",
        }

        metadata = extract_file_metadata(file_data)

        assert metadata["has_thumbnail"] is True
        assert "thumbnail" not in metadata
        assert metadata["thumbnail_status"] == "ready"

    def test_extract_preserves_other_fields(self):
        """Test that other fields are preserved."""
        from src.db.models import extract_file_metadata

        file_data = {
            "name": "photo.jpg",
            "type": "image/jpeg",
            "data": "aGVsbG8=",
            "custom_field": "preserved",
        }

        metadata = extract_file_metadata(file_data)

        assert metadata["custom_field"] == "preserved"
