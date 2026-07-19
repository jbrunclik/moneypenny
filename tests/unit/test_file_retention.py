"""Tests for media retention helpers."""

import base64
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from src.db.models import make_blob_key, make_thumbnail_key
from src.utils.datetime_utils import utcnow_naive
from src.utils.file_retention import (
    cleanup_expired_files,
    is_file_expired,
    retention_days_for_mime,
    retention_note,
    run_file_cleanup_if_due,
)


class TestRetentionDays:
    def test_video_retention(self) -> None:
        assert retention_days_for_mime("video/mp4") == 7
        assert retention_days_for_mime("video/quicktime") == 7

    def test_image_retention(self) -> None:
        assert retention_days_for_mime("image/png") == 30

    def test_other_files_use_file_retention(self) -> None:
        assert retention_days_for_mime("application/pdf") == 30
        assert retention_days_for_mime("text/plain") == 30


class TestIsMediaExpired:
    def test_fresh_video_not_expired(self) -> None:
        now = datetime(2026, 7, 19, 12, 0)
        created = now - timedelta(days=6)
        assert not is_file_expired("video/mp4", created, now=now)

    def test_old_video_expired(self) -> None:
        now = datetime(2026, 7, 19, 12, 0)
        created = now - timedelta(days=8)
        assert is_file_expired("video/mp4", created, now=now)

    def test_image_expires_after_30_days(self) -> None:
        now = datetime(2026, 7, 19, 12, 0)
        assert not is_file_expired("image/png", now - timedelta(days=29), now=now)
        assert is_file_expired("image/png", now - timedelta(days=31), now=now)

    def test_pdf_expires_after_file_retention(self) -> None:
        now = datetime(2026, 7, 19, 12, 0)
        assert not is_file_expired("application/pdf", now - timedelta(days=29), now=now)
        assert is_file_expired("application/pdf", now - timedelta(days=31), now=now)

    def test_defaults_to_current_time(self) -> None:
        assert is_file_expired("video/mp4", datetime.now() - timedelta(days=8))
        assert not is_file_expired("video/mp4", datetime.now())


class TestRetentionNote:
    def test_notes(self) -> None:
        assert "7 days" in retention_note("video/mp4")
        assert "30 days" in retention_note("image/png")
        assert "30 days" in retention_note("application/pdf")
        assert retention_note("application/pdf").startswith("Files")


# =============================================================================
# Sweep job tests
# =============================================================================


@pytest.fixture
def seeded_env(test_database, test_blob_store):
    """Patch module-level db/blob_store lookups to the isolated test instances."""
    with (
        patch("src.db.models.db", test_database),
        patch("src.db.blob_store.get_blob_store", return_value=test_blob_store),
        patch("src.db.models.message.get_blob_store", return_value=test_blob_store),
        patch("src.db.models.helpers.get_blob_store", return_value=test_blob_store),
        patch("src.agent.gemini_files.db", test_database),
    ):
        user = test_database.get_or_create_user(email="t@example.com", name="T")
        conv = test_database.create_conversation(user.id)
        yield test_database, test_blob_store, conv.id


def _seed(db, blob_store, conversation_id, mime, days_old, data=b"blob-data"):
    """Insert a message with one file + blob, created days_old ago."""
    ext = "mp4" if mime.startswith("video/") else "png"
    msg = db.add_message(
        conversation_id,
        "user",
        "here is a file",
        files=[
            {
                "name": f"f.{ext}",
                "type": mime,
                "size": len(data),
                "data": base64.b64encode(data).decode("utf-8"),
            }
        ],
    )
    backdated = (datetime.now() - timedelta(days=days_old)).isoformat()
    with db._pool.get_connection() as conn:
        conn.execute("UPDATE messages SET created_at = ? WHERE id = ?", (backdated, msg.id))
        conn.commit()
    # add_message saved the blob via the patched get_blob_store already;
    # assert it exists so the test setup is trustworthy
    assert blob_store.get(make_blob_key(msg.id, 0)) is not None
    return msg.id


class TestCleanupExpiredMedia:
    def test_deletes_expired_video_blob(self, seeded_env) -> None:
        db, blob_store, conv_id = seeded_env
        msg_id = _seed(db, blob_store, conv_id, "video/mp4", days_old=8)
        counts = cleanup_expired_files()
        assert counts["videos_deleted"] == 1
        assert blob_store.get(make_blob_key(msg_id, 0)) is None

    def test_keeps_fresh_video(self, seeded_env) -> None:
        db, blob_store, conv_id = seeded_env
        msg_id = _seed(db, blob_store, conv_id, "video/mp4", days_old=3)
        cleanup_expired_files()
        assert blob_store.get(make_blob_key(msg_id, 0)) is not None

    def test_deletes_old_image_but_keeps_thumbnail(self, seeded_env) -> None:
        db, blob_store, conv_id = seeded_env
        msg_id = _seed(db, blob_store, conv_id, "image/png", days_old=31)
        blob_store.save(make_thumbnail_key(msg_id, 0), b"thumb", "image/jpeg")
        counts = cleanup_expired_files()
        assert counts["images_deleted"] == 1
        assert blob_store.get(make_blob_key(msg_id, 0)) is None
        assert blob_store.get(make_thumbnail_key(msg_id, 0)) is not None

    def test_image_between_windows_kept(self, seeded_env) -> None:
        db, blob_store, conv_id = seeded_env
        msg_id = _seed(db, blob_store, conv_id, "image/png", days_old=10)
        cleanup_expired_files()
        assert blob_store.get(make_blob_key(msg_id, 0)) is not None

    def test_deletes_old_generic_file(self, seeded_env) -> None:
        db, blob_store, conv_id = seeded_env
        msg_id = _seed(db, blob_store, conv_id, "application/pdf", days_old=31)
        counts = cleanup_expired_files()
        assert counts["files_deleted"] == 1
        assert blob_store.get(make_blob_key(msg_id, 0)) is None

    def test_deletes_gemini_uri_cache_for_videos(self, seeded_env) -> None:
        db, blob_store, conv_id = seeded_env
        msg_id = _seed(db, blob_store, conv_id, "video/mp4", days_old=8)
        db.kv_set("_system", "gemini_files", f"{msg_id}:0", '{"uri": "x"}')
        cleanup_expired_files()
        assert db.kv_get("_system", "gemini_files", f"{msg_id}:0") is None

    def test_idempotent(self, seeded_env) -> None:
        db, blob_store, conv_id = seeded_env
        _seed(db, blob_store, conv_id, "video/mp4", days_old=8)
        cleanup_expired_files()
        counts = cleanup_expired_files()
        assert counts == {"videos_deleted": 0, "images_deleted": 0, "files_deleted": 0}


class TestRunIfDue:
    def test_skips_when_ran_recently(self, seeded_env) -> None:
        db, _, _ = seeded_env
        db.kv_set("_system", "file_cleanup", "last_run", utcnow_naive().isoformat())
        assert run_file_cleanup_if_due() is False

    def test_runs_and_stamps_when_due(self, seeded_env) -> None:
        db, _, _ = seeded_env
        assert run_file_cleanup_if_due() is True
        assert db.kv_get("_system", "file_cleanup", "last_run") is not None
