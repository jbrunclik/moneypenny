"""Unit tests for database backup script."""

import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.backup_databases import (
    BACKUP_DIR_NAME,
    DEFAULT_RETENTION_DAYS,
    cleanup_old_backups,
    create_backup,
    get_backup_dir,
    list_backups,
)


class TestGetBackupDir:
    """Test backup directory path generation."""

    def test_basic_path(self):
        """Test backup directory is created in correct location."""
        db_path = Path("/data/chatbot.db")
        backup_dir = get_backup_dir(db_path)
        assert backup_dir == Path("/data/backups/chatbot.db")

    def test_preserves_db_name(self):
        """Test that database name is preserved in backup path."""
        db_path = Path("/app/files.db")
        backup_dir = get_backup_dir(db_path)
        assert backup_dir == Path("/app/backups/files.db")


class TestCreateBackup:
    """Test backup creation."""

    @pytest.fixture
    def test_db(self):
        """Create a temporary database with test data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, data TEXT)")
            conn.execute("INSERT INTO test (data) VALUES ('hello')")
            conn.commit()
            conn.close()
            yield db_path

    def test_creates_backup(self, test_db):
        """Test that backup file is created."""
        result = create_backup(test_db, "Test DB")
        assert result is True

        backup_dir = get_backup_dir(test_db)
        backups = list(backup_dir.glob("*.db"))
        assert len(backups) == 1

    def test_backup_contains_data(self, test_db):
        """Test that backup contains the original data."""
        create_backup(test_db, "Test DB")

        backup_dir = get_backup_dir(test_db)
        backup_file = list(backup_dir.glob("*.db"))[0]

        # Verify backup contains data
        conn = sqlite3.connect(str(backup_file))
        result = conn.execute("SELECT data FROM test").fetchone()
        conn.close()

        assert result[0] == "hello"

    def test_skips_nonexistent_db(self):
        """Test that nonexistent database is skipped gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "nonexistent.db"
            result = create_backup(db_path, "Nonexistent DB")
            assert result is True  # Should succeed (skip) without error

    def test_backup_while_writing(self, test_db):
        """Test that backup works while database is open."""
        # Keep a connection open
        conn = sqlite3.connect(str(test_db))
        try:
            # Backup should still work
            result = create_backup(test_db, "Test DB")
            assert result is True
        finally:
            conn.close()

    def test_backup_filename_format(self, test_db):
        """Test that backup filename has correct format."""
        create_backup(test_db, "Test DB")

        backup_dir = get_backup_dir(test_db)
        backup_file = list(backup_dir.glob("*.db"))[0]

        # Filename should be: {stem}-YYYYMMDD-HHMMSS.db
        name = backup_file.stem
        assert name.startswith("test-")
        # Should have timestamp in format YYYYMMDD-HHMMSS
        timestamp_part = name.replace("test-", "")
        datetime.strptime(timestamp_part, "%Y%m%d-%H%M%S")  # Should not raise


class TestCleanupOldBackups:
    """Test backup retention cleanup."""

    @pytest.fixture
    def backup_dir_with_files(self):
        """Create a backup directory with test files of various ages."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            backup_dir = get_backup_dir(db_path)
            backup_dir.mkdir(parents=True)

            now = datetime.now(UTC)

            # Create backups of various ages
            files = []
            for days_ago in [0, 1, 5, 7, 8, 14, 30]:
                timestamp = now - timedelta(days=days_ago)
                filename = f"test-{timestamp.strftime('%Y%m%d-%H%M%S')}.db"
                filepath = backup_dir / filename
                filepath.write_bytes(b"backup data")
                files.append((filepath, days_ago))

            yield db_path, files

    def test_removes_old_backups(self, backup_dir_with_files):
        """Test that backups older than retention are removed."""
        db_path, files = backup_dir_with_files

        # Keep 7 days
        removed = cleanup_old_backups(db_path, "Test DB", retention_days=7)

        # Should remove backups older than 7 days: 8, 14, 30 days old
        assert removed == 3

        backup_dir = get_backup_dir(db_path)
        remaining = list(backup_dir.glob("*.db"))
        assert len(remaining) == 4  # 0, 1, 5, 7 days old

    def test_keeps_recent_backups(self, backup_dir_with_files):
        """Test that recent backups are kept."""
        db_path, files = backup_dir_with_files

        cleanup_old_backups(db_path, "Test DB", retention_days=7)

        # Check that recent backups still exist
        for filepath, days_ago in files:
            if days_ago <= 7:
                assert filepath.exists(), f"Backup {days_ago} days old should exist"
            else:
                assert not filepath.exists(), f"Backup {days_ago} days old should be removed"

    def test_handles_empty_directory(self):
        """Test cleanup with no backups."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            removed = cleanup_old_backups(db_path, "Test DB", retention_days=7)
            assert removed == 0

    def test_handles_nonexistent_directory(self):
        """Test cleanup when backup directory doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "subdir" / "test.db"
            removed = cleanup_old_backups(db_path, "Test DB", retention_days=7)
            assert removed == 0


class TestListBackups:
    """Test backup listing functionality."""

    @pytest.fixture
    def backup_dir_with_files(self):
        """Create a backup directory with test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            backup_dir = get_backup_dir(db_path)
            backup_dir.mkdir(parents=True)

            now = datetime.now(UTC)

            # Create backups with different timestamps and sizes
            for days_ago, size in [(0, 1000), (1, 2000), (2, 3000)]:
                timestamp = now - timedelta(days=days_ago)
                filename = f"test-{timestamp.strftime('%Y%m%d-%H%M%S')}.db"
                filepath = backup_dir / filename
                filepath.write_bytes(b"x" * size)

            yield db_path

    def test_lists_backups(self, backup_dir_with_files):
        """Test that backups are listed correctly."""
        backups = list_backups(backup_dir_with_files)
        assert len(backups) == 3

    def test_sorted_newest_first(self, backup_dir_with_files):
        """Test that backups are sorted newest first."""
        backups = list_backups(backup_dir_with_files)

        timestamps = [b[2] for b in backups]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_returns_correct_sizes(self, backup_dir_with_files):
        """Test that backup sizes are correct."""
        backups = list_backups(backup_dir_with_files)

        # Newest (0 days ago) should be 1000 bytes
        assert backups[0][1] == 1000

    def test_empty_when_no_backups(self):
        """Test empty list when no backups exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            backups = list_backups(db_path)
            assert backups == []


class TestDefaultRetention:
    """Test default retention value."""

    def test_default_retention_is_7_days(self):
        """Test that default retention is 7 days."""
        assert DEFAULT_RETENTION_DAYS == 7


class TestBackupDirName:
    """Test backup directory constant."""

    def test_backup_dir_name(self):
        """Test backup directory name constant."""
        assert BACKUP_DIR_NAME == "backups"
