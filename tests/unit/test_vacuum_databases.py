"""Unit tests for database vacuum script."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

from scripts.vacuum_databases import main, vacuum_database


class TestVacuumDatabase:
    """Test the vacuum_database function."""

    def test_vacuum_success(self, tmp_path: Path):
        """Test successful vacuum of a database with data."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, data TEXT)")
        conn.executemany("INSERT INTO t (data) VALUES (?)", [("x" * 1000,)] * 100)
        conn.execute("DELETE FROM t WHERE id > 50")
        conn.commit()
        conn.close()

        result = vacuum_database(db_path, "test db")

        assert result is True

    def test_vacuum_nonexistent_db(self, tmp_path: Path):
        """Test that nonexistent database is skipped (returns True)."""
        db_path = tmp_path / "nonexistent.db"

        result = vacuum_database(db_path, "missing db")

        assert result is True

    def test_vacuum_sqlite_error(self, tmp_path: Path):
        """Test that SQLite errors return False."""
        db_path = tmp_path / "test.db"
        # Create a valid DB so the exists() check passes
        conn = sqlite3.connect(str(db_path))
        conn.close()

        with patch("scripts.vacuum_databases.sqlite3.connect", side_effect=sqlite3.Error("locked")):
            result = vacuum_database(db_path, "locked db")

        assert result is False

    def test_vacuum_empty_database(self, tmp_path: Path):
        """Test vacuum on an empty database succeeds."""
        db_path = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db_path))
        conn.close()

        result = vacuum_database(db_path, "empty db")

        assert result is True


class TestMain:
    """Test the main function."""

    def test_main_all_success(self, tmp_path: Path):
        """Test main returns 0 when all databases vacuum successfully."""
        db1 = tmp_path / "chatbot.db"
        db2 = tmp_path / "files.db"
        for p in (db1, db2):
            conn = sqlite3.connect(str(p))
            conn.close()

        with (
            patch("scripts.vacuum_databases.Config.DATABASE_PATH", db1),
            patch("scripts.vacuum_databases.Config.BLOB_STORAGE_PATH", db2),
        ):
            result = main()

        assert result == 0

    def test_main_partial_failure(self):
        """Test main returns 1 when one database fails to vacuum."""
        with patch("scripts.vacuum_databases.vacuum_database", side_effect=[True, False]):
            result = main()

        assert result == 1

    def test_main_nonexistent_databases(self, tmp_path: Path):
        """Test main returns 0 when databases don't exist yet (skipped)."""
        with (
            patch("scripts.vacuum_databases.Config.DATABASE_PATH", tmp_path / "missing1.db"),
            patch("scripts.vacuum_databases.Config.BLOB_STORAGE_PATH", tmp_path / "missing2.db"),
        ):
            result = main()

        assert result == 0
