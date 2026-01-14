"""Unit tests for database connectivity checking."""

import os
import sqlite3
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    pass

from src.db.models import check_database_connectivity


class TestCheckDatabaseConnectivity:
    """Tests for check_database_connectivity function."""

    def test_successful_connection(self, tmp_path: Path) -> None:
        """Should return success for valid database path."""
        db_path = tmp_path / "test.db"
        success, error = check_database_connectivity(db_path)

        assert success is True
        assert error is None
        # Verify database file was created
        assert db_path.exists()

    def test_successful_connection_existing_db(self, tmp_path: Path) -> None:
        """Should return success for existing database file."""
        db_path = tmp_path / "existing.db"
        # Create existing database
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.close()

        success, error = check_database_connectivity(db_path)

        assert success is True
        assert error is None

    def test_missing_parent_directory(self, tmp_path: Path) -> None:
        """Should fail with clear message for missing directory."""
        db_path = tmp_path / "nonexistent" / "subdir" / "test.db"
        success, error = check_database_connectivity(db_path)

        assert success is False
        assert error is not None
        assert "does not exist" in error
        assert "nonexistent" in error

    def test_readonly_directory(self, tmp_path: Path) -> None:
        """Should fail for non-writable directory."""
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        original_mode = readonly_dir.stat().st_mode
        os.chmod(readonly_dir, 0o444)  # Read-only

        try:
            db_path = readonly_dir / "test.db"
            success, error = check_database_connectivity(db_path)

            assert success is False
            assert error is not None
            assert "not writable" in error
        finally:
            os.chmod(readonly_dir, original_mode)  # Restore for cleanup

    def test_readonly_database_file(self, tmp_path: Path) -> None:
        """Should fail for non-writable database file."""
        db_path = tmp_path / "readonly.db"
        # Create database first
        conn = sqlite3.connect(db_path)
        conn.close()

        original_mode = db_path.stat().st_mode
        os.chmod(db_path, 0o444)  # Read-only

        try:
            success, error = check_database_connectivity(db_path)

            assert success is False
            assert error is not None
            assert "not readable/writable" in error
        finally:
            os.chmod(db_path, original_mode)  # Restore for cleanup

    def test_database_locked_error(self, tmp_path: Path) -> None:
        """Should handle database locked errors gracefully."""
        db_path = tmp_path / "test.db"

        with patch("sqlite3.connect") as mock_connect:
            mock_connect.side_effect = sqlite3.OperationalError("database is locked")
            success, error = check_database_connectivity(db_path)

            assert success is False
            assert error is not None
            assert "locked" in error.lower()
            assert "Another process" in error

    def test_disk_io_error(self, tmp_path: Path) -> None:
        """Should handle disk I/O errors gracefully."""
        db_path = tmp_path / "test.db"

        with patch("sqlite3.connect") as mock_connect:
            mock_connect.side_effect = sqlite3.OperationalError("disk I/O error")
            success, error = check_database_connectivity(db_path)

            assert success is False
            assert error is not None
            assert "I/O" in error
            assert "disk health" in error.lower()

    def test_unable_to_open_database(self, tmp_path: Path) -> None:
        """Should handle unable to open database errors."""
        db_path = tmp_path / "test.db"

        with patch("sqlite3.connect") as mock_connect:
            mock_connect.side_effect = sqlite3.OperationalError("unable to open database file")
            success, error = check_database_connectivity(db_path)

            assert success is False
            assert error is not None
            assert "Cannot open database" in error
            assert "permissions" in error.lower()

    def test_generic_operational_error(self, tmp_path: Path) -> None:
        """Should handle generic SQLite operational errors."""
        db_path = tmp_path / "test.db"

        with patch("sqlite3.connect") as mock_connect:
            mock_connect.side_effect = sqlite3.OperationalError("some unknown error")
            success, error = check_database_connectivity(db_path)

            assert success is False
            assert error is not None
            assert "Database error" in error
            assert "some unknown error" in error

    def test_unexpected_exception(self, tmp_path: Path) -> None:
        """Should handle unexpected exceptions gracefully."""
        db_path = tmp_path / "test.db"

        with patch("sqlite3.connect") as mock_connect:
            mock_connect.side_effect = RuntimeError("Unexpected error")
            success, error = check_database_connectivity(db_path)

            assert success is False
            assert error is not None
            assert "Unexpected database error" in error
            assert "Unexpected error" in error

    def test_uses_config_path_by_default(self) -> None:
        """Should use Config.DATABASE_PATH when no path is provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = Path(tmpdir) / "config_default.db"

            with patch("src.db.models.helpers.Config") as mock_config:
                mock_config.DATABASE_PATH = test_path
                success, error = check_database_connectivity()

                assert success is True
                assert error is None
                assert test_path.exists()
