"""Tests for media retention helpers."""

from datetime import datetime, timedelta

from src.utils.media_retention import (
    is_media_expired,
    retention_days_for_mime,
    retention_note,
)


class TestRetentionDays:
    def test_video_retention(self) -> None:
        assert retention_days_for_mime("video/mp4") == 7
        assert retention_days_for_mime("video/quicktime") == 7

    def test_image_retention(self) -> None:
        assert retention_days_for_mime("image/png") == 30

    def test_non_media_has_no_retention(self) -> None:
        assert retention_days_for_mime("application/pdf") is None
        assert retention_days_for_mime("text/plain") is None


class TestIsMediaExpired:
    def test_fresh_video_not_expired(self) -> None:
        now = datetime(2026, 7, 19, 12, 0)
        created = now - timedelta(days=6)
        assert not is_media_expired("video/mp4", created, now=now)

    def test_old_video_expired(self) -> None:
        now = datetime(2026, 7, 19, 12, 0)
        created = now - timedelta(days=8)
        assert is_media_expired("video/mp4", created, now=now)

    def test_image_expires_after_30_days(self) -> None:
        now = datetime(2026, 7, 19, 12, 0)
        assert not is_media_expired("image/png", now - timedelta(days=29), now=now)
        assert is_media_expired("image/png", now - timedelta(days=31), now=now)

    def test_pdf_never_expires(self) -> None:
        now = datetime(2026, 7, 19, 12, 0)
        assert not is_media_expired("application/pdf", now - timedelta(days=999), now=now)

    def test_defaults_to_current_time(self) -> None:
        assert is_media_expired("video/mp4", datetime.now() - timedelta(days=8))
        assert not is_media_expired("video/mp4", datetime.now())


class TestRetentionNote:
    def test_notes(self) -> None:
        assert "7 days" in retention_note("video/mp4")
        assert "30 days" in retention_note("image/png")
