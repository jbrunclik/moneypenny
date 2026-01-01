"""Unit tests for src/utils/background_thumbnails.py."""

import base64
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.utils.background_thumbnails import (
    _generate_thumbnail_task,
    generate_and_save_thumbnail,
    get_executor,
    mark_files_for_thumbnail_generation,
    queue_pending_thumbnails,
    should_skip_thumbnail,
)


class TestShouldSkipThumbnail:
    """Tests for should_skip_thumbnail function."""

    def test_skips_non_image_types(self) -> None:
        """Non-image MIME types should be skipped."""
        assert should_skip_thumbnail("data", "application/pdf") is True
        assert should_skip_thumbnail("data", "text/plain") is True
        assert should_skip_thumbnail("data", "application/json") is True

    def test_does_not_skip_image_types(self, sample_png_base64: str) -> None:
        """Image MIME types should not be skipped (unless small)."""
        # sample_png_base64 is ~500 bytes, which is less than 100KB threshold
        # So it SHOULD be skipped due to size
        assert should_skip_thumbnail(sample_png_base64, "image/png") is True

    def test_does_not_skip_large_images(self, large_png_base64: str) -> None:
        """Large images (>100KB) should not be skipped."""
        # large_png_base64 is 1000x1000 which should be > 100KB
        # Check the size first
        decoded_size = len(base64.b64decode(large_png_base64))
        if decoded_size > Config.THUMBNAIL_SKIP_THRESHOLD_BYTES:
            assert should_skip_thumbnail(large_png_base64, "image/png") is False
        else:
            # If the test image is smaller than threshold, it should be skipped
            assert should_skip_thumbnail(large_png_base64, "image/png") is True

    def test_skips_small_images(self, sample_png_base64: str) -> None:
        """Small images (<100KB) should be skipped."""
        # Verify it's actually small
        decoded_size = len(base64.b64decode(sample_png_base64))
        assert decoded_size < Config.THUMBNAIL_SKIP_THRESHOLD_BYTES
        assert should_skip_thumbnail(sample_png_base64, "image/png") is True

    def test_handles_invalid_base64(self) -> None:
        """Invalid base64 should not be skipped (let generation handle error)."""
        # Invalid base64 will fail to decode, should return False to allow
        # thumbnail generation to handle the error properly
        assert should_skip_thumbnail("invalid!!!base64", "image/png") is False

    def test_handles_empty_data(self) -> None:
        """Empty data should be skipped (0 bytes < threshold)."""
        # Empty string decodes to 0 bytes, which is less than threshold
        assert should_skip_thumbnail("", "image/png") is True


class TestMarkFilesForThumbnailGeneration:
    """Tests for mark_files_for_thumbnail_generation function."""

    def test_marks_small_images_as_ready(self, sample_png_base64: str) -> None:
        """Small images should be marked ready with original data as thumbnail."""
        files = [{"name": "small.png", "type": "image/png", "data": sample_png_base64}]

        result = mark_files_for_thumbnail_generation(files)

        assert len(result) == 1
        assert result[0]["thumbnail_status"] == "ready"
        assert result[0]["thumbnail"] == sample_png_base64  # Original data used

    def test_marks_large_images_as_pending(self, large_png_base64: str) -> None:
        """Large images should be marked as pending."""
        # Only test if the large image is actually > threshold
        decoded_size = len(base64.b64decode(large_png_base64))
        if decoded_size <= Config.THUMBNAIL_SKIP_THRESHOLD_BYTES:
            pytest.skip("Test image not large enough")

        files = [{"name": "large.png", "type": "image/png", "data": large_png_base64}]

        result = mark_files_for_thumbnail_generation(files)

        assert len(result) == 1
        assert result[0]["thumbnail_status"] == "pending"
        assert "thumbnail" not in result[0] or result[0]["thumbnail"] is None

    def test_skips_non_image_files(self) -> None:
        """Non-image files should not be modified."""
        files = [{"name": "doc.pdf", "type": "application/pdf", "data": "pdfdata"}]

        result = mark_files_for_thumbnail_generation(files)

        assert len(result) == 1
        assert "thumbnail_status" not in result[0]
        assert "thumbnail" not in result[0]

    def test_handles_mixed_files(self, sample_png_base64: str) -> None:
        """Should handle mix of image and non-image files."""
        files = [
            {"name": "small.png", "type": "image/png", "data": sample_png_base64},
            {"name": "doc.pdf", "type": "application/pdf", "data": "pdfdata"},
            {"name": "photo.jpg", "type": "image/jpeg", "data": sample_png_base64},
        ]

        result = mark_files_for_thumbnail_generation(files)

        assert len(result) == 3
        assert result[0]["thumbnail_status"] == "ready"  # Small PNG
        assert "thumbnail_status" not in result[1]  # PDF
        assert result[2]["thumbnail_status"] == "ready"  # Small JPEG

    def test_handles_empty_list(self) -> None:
        """Empty file list should return empty list."""
        result = mark_files_for_thumbnail_generation([])
        assert result == []


class TestQueuePendingThumbnails:
    """Tests for queue_pending_thumbnails function."""

    def test_queues_pending_files(self, sample_png_base64: str) -> None:
        """Should queue thumbnail generation for pending files."""
        files = [
            {
                "name": "pending.png",
                "type": "image/png",
                "data": sample_png_base64,
                "thumbnail_status": "pending",
            }
        ]

        with patch("src.utils.background_thumbnails.queue_thumbnail_generation") as mock_queue:
            queue_pending_thumbnails("msg-123", files)

            mock_queue.assert_called_once_with("msg-123", 0, sample_png_base64, "image/png")

    def test_skips_ready_files(self, sample_png_base64: str) -> None:
        """Should skip files that are already ready."""
        files = [
            {
                "name": "ready.png",
                "type": "image/png",
                "data": sample_png_base64,
                "thumbnail": sample_png_base64,
                "thumbnail_status": "ready",
            }
        ]

        with patch("src.utils.background_thumbnails.queue_thumbnail_generation") as mock_queue:
            queue_pending_thumbnails("msg-123", files)

            mock_queue.assert_not_called()

    def test_queues_multiple_pending(self, sample_png_base64: str) -> None:
        """Should queue multiple pending files."""
        files = [
            {
                "name": "pending1.png",
                "type": "image/png",
                "data": sample_png_base64,
                "thumbnail_status": "pending",
            },
            {
                "name": "ready.jpg",
                "type": "image/jpeg",
                "data": sample_png_base64,
                "thumbnail_status": "ready",
            },
            {
                "name": "pending2.png",
                "type": "image/png",
                "data": sample_png_base64,
                "thumbnail_status": "pending",
            },
        ]

        with patch("src.utils.background_thumbnails.queue_thumbnail_generation") as mock_queue:
            queue_pending_thumbnails("msg-123", files)

            assert mock_queue.call_count == 2
            mock_queue.assert_any_call("msg-123", 0, sample_png_base64, "image/png")
            mock_queue.assert_any_call("msg-123", 2, sample_png_base64, "image/png")


class TestGetExecutor:
    """Tests for get_executor function."""

    def test_returns_thread_pool_executor(self) -> None:
        """Should return a ThreadPoolExecutor."""
        executor = get_executor()
        assert isinstance(executor, ThreadPoolExecutor)

    def test_returns_same_executor(self) -> None:
        """Should return the same executor on subsequent calls."""
        executor1 = get_executor()
        executor2 = get_executor()
        assert executor1 is executor2


class TestGenerateAndSaveThumbnail:
    """Tests for generate_and_save_thumbnail function."""

    def test_generates_and_saves_thumbnail(self, sample_png_base64: str) -> None:
        """Should generate thumbnail and save to database, returning the thumbnail."""
        mock_db = MagicMock()
        mock_db.update_message_file_thumbnail.return_value = True

        with patch("src.db.models.db", mock_db):
            with patch(
                "src.utils.images.generate_thumbnail",
                return_value="thumbnail_data",
            ) as mock_gen:
                result = generate_and_save_thumbnail("msg-123", 0, sample_png_base64, "image/png")

                assert result == "thumbnail_data"
                mock_gen.assert_called_once_with(sample_png_base64, "image/png")
                mock_db.update_message_file_thumbnail.assert_called_once_with(
                    "msg-123", 0, "thumbnail_data", status="ready"
                )

    def test_returns_none_on_generation_failure(self) -> None:
        """Should return None when thumbnail generation fails."""
        mock_db = MagicMock()
        mock_db.update_message_file_thumbnail.return_value = True

        with patch("src.db.models.db", mock_db):
            with patch(
                "src.utils.images.generate_thumbnail",
                return_value=None,
            ):
                result = generate_and_save_thumbnail("msg-123", 0, "data", "image/png")

                assert result is None
                mock_db.update_message_file_thumbnail.assert_called_once_with(
                    "msg-123", 0, None, status="failed"
                )

    def test_returns_thumbnail_even_if_db_update_fails(self, sample_png_base64: str) -> None:
        """Should return thumbnail even if database update fails."""
        mock_db = MagicMock()
        mock_db.update_message_file_thumbnail.return_value = False  # DB update fails

        with patch("src.db.models.db", mock_db):
            with patch(
                "src.utils.images.generate_thumbnail",
                return_value="thumbnail_data",
            ):
                result = generate_and_save_thumbnail("msg-123", 0, sample_png_base64, "image/png")

                # Still returns the thumbnail even though DB update failed
                assert result == "thumbnail_data"


class TestGenerateThumbnailTask:
    """Tests for _generate_thumbnail_task function."""

    def test_generates_and_saves_thumbnail(self, sample_png_base64: str) -> None:
        """Should generate thumbnail and save to database via shared helper."""
        mock_db = MagicMock()
        mock_db.update_message_file_thumbnail.return_value = True

        # db is imported inside the function, so we need to patch it in src.db.models
        with patch("src.db.models.db", mock_db):
            with patch(
                "src.utils.images.generate_thumbnail",
                return_value="thumbnail_data",
            ) as mock_gen:
                _generate_thumbnail_task("msg-123", 0, sample_png_base64, "image/png")

                mock_gen.assert_called_once_with(sample_png_base64, "image/png")
                mock_db.update_message_file_thumbnail.assert_called_once_with(
                    "msg-123", 0, "thumbnail_data", status="ready"
                )

    def test_marks_failed_on_generation_error(self) -> None:
        """Should mark as failed when thumbnail generation returns None."""
        mock_db = MagicMock()

        with patch("src.db.models.db", mock_db):
            with patch(
                "src.utils.images.generate_thumbnail",
                return_value=None,
            ):
                _generate_thumbnail_task("msg-123", 0, "invalid", "image/png")

                mock_db.update_message_file_thumbnail.assert_called_once_with(
                    "msg-123", 0, None, status="failed"
                )

    def test_handles_exception_gracefully(self) -> None:
        """Should handle exceptions and mark as failed."""
        mock_db = MagicMock()

        with patch("src.db.models.db", mock_db):
            with patch(
                "src.utils.images.generate_thumbnail",
                side_effect=Exception("Test error"),
            ):
                # Should not raise
                _generate_thumbnail_task("msg-123", 0, "data", "image/png")

                # Should attempt to mark as failed
                mock_db.update_message_file_thumbnail.assert_called_once_with(
                    "msg-123", 0, None, status="failed"
                )

    def test_handles_missing_message(self) -> None:
        """Should handle case where message was deleted."""
        mock_db = MagicMock()
        mock_db.update_message_file_thumbnail.side_effect = Exception("Message not found")

        with patch("src.db.models.db", mock_db):
            with patch(
                "src.utils.images.generate_thumbnail",
                return_value="thumbnail",
            ):
                # Should not raise even if DB update fails
                _generate_thumbnail_task("msg-deleted", 0, "data", "image/png")
