"""Unit tests for database query logging."""

import logging
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from src.db.models import Database


class TestSlowQueryLogging:
    """Tests for slow query detection and logging."""

    def test_slow_query_logs_warning(
        self, test_database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should log warning for queries exceeding threshold."""
        # Set very low threshold to trigger slow query logging
        test_database._should_log_queries = True
        test_database._slow_query_threshold_ms = 0  # Everything is slow

        with caplog.at_level(logging.WARNING, logger="src.utils.db_helpers"):
            test_database.get_or_create_user("slow@example.com", "Slow User")

        assert any("Slow query" in record.message for record in caplog.records)

    def test_query_logging_includes_timing(
        self, test_database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should include elapsed_ms in slow query log."""
        test_database._should_log_queries = True
        test_database._slow_query_threshold_ms = 0

        with caplog.at_level(logging.WARNING, logger="src.utils.db_helpers"):
            test_database.get_or_create_user("timing@example.com", "Timing User")

        # Find the slow query log record
        slow_query_records = [r for r in caplog.records if "Slow query" in r.message]
        assert len(slow_query_records) > 0
        record = slow_query_records[0]
        assert "elapsed_ms" in record.__dict__

    def test_query_logging_truncates_long_queries(
        self, test_database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should truncate long queries in logs."""
        test_database._should_log_queries = True
        test_database._slow_query_threshold_ms = 0

        with caplog.at_level(logging.WARNING, logger="src.utils.db_helpers"):
            test_database.get_or_create_user("truncate@example.com", "Truncate User")

        # Find the slow query log record
        slow_query_records = [r for r in caplog.records if "Slow query" in r.message]
        assert len(slow_query_records) > 0
        record = slow_query_records[0]
        assert "query_snippet" in record.__dict__
        # Query snippet should be reasonable length
        assert len(record.query_snippet) <= 203  # 200 + "..."

    def test_query_logging_truncates_long_params(
        self, test_database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should truncate long params in logs to avoid logging sensitive data."""
        test_database._should_log_queries = True
        test_database._slow_query_threshold_ms = 0

        with caplog.at_level(logging.WARNING, logger="src.utils.db_helpers"):
            # Create user with long name to test param truncation
            test_database.get_or_create_user("params@example.com", "A" * 200)

        slow_query_records = [r for r in caplog.records if "Slow query" in r.message]
        assert len(slow_query_records) > 0
        record = slow_query_records[0]
        assert "params_snippet" in record.__dict__
        # Params snippet should be truncated
        assert len(record.params_snippet) <= 103  # 100 + "..."

    def test_no_query_logging_when_disabled(
        self, test_database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should not log queries when logging is disabled."""
        test_database._should_log_queries = False

        with caplog.at_level(logging.DEBUG, logger="src.utils.db_helpers"):
            test_database.get_or_create_user("nolog@example.com", "No Log User")

        slow_query_records = [r for r in caplog.records if "Slow query" in r.message]
        assert len(slow_query_records) == 0

    def test_fast_query_not_logged_as_slow(
        self, test_database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should not log fast queries as slow."""
        test_database._should_log_queries = True
        test_database._slow_query_threshold_ms = 10000  # 10 seconds

        with caplog.at_level(logging.WARNING, logger="src.utils.db_helpers"):
            test_database.get_or_create_user("fast@example.com", "Fast User")

        slow_query_records = [r for r in caplog.records if "Slow query" in r.message]
        assert len(slow_query_records) == 0

    def test_debug_logging_when_enabled(
        self, test_database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should log all queries at DEBUG level when LOG_LEVEL is DEBUG."""
        test_database._should_log_queries = True
        test_database._slow_query_threshold_ms = 10000  # High threshold

        with patch("src.utils.db_helpers.Config.LOG_LEVEL", "DEBUG"):
            with caplog.at_level(logging.DEBUG, logger="src.utils.db_helpers"):
                test_database.get_or_create_user("debug@example.com", "Debug User")

        query_records = [r for r in caplog.records if "Query executed" in r.message]
        assert len(query_records) > 0

    def test_execute_with_timing_returns_cursor(self, test_database: Database) -> None:
        """Should return valid cursor from _execute_with_timing."""
        test_database._should_log_queries = True

        with test_database._pool.get_connection() as conn:
            cursor = test_database._execute_with_timing(conn, "SELECT 1 as result", ())
            row = cursor.fetchone()
            assert row["result"] == 1

    def test_execute_with_timing_works_without_params(self, test_database: Database) -> None:
        """Should work correctly without query parameters."""
        test_database._should_log_queries = True
        test_database._slow_query_threshold_ms = 0

        with test_database._pool.get_connection() as conn:
            cursor = test_database._execute_with_timing(conn, "SELECT 1")
            row = cursor.fetchone()
            assert row[0] == 1

    def test_slow_query_threshold_from_config(self, tmp_path: Path) -> None:
        """Should use SLOW_QUERY_THRESHOLD_MS from Config."""
        with patch("src.utils.db_helpers.Config") as mock_config:
            mock_config.SLOW_QUERY_THRESHOLD_MS = 500
            mock_config.LOG_LEVEL = "INFO"
            mock_config.is_development.return_value = True

            from src.db.models import Database

            db = Database(db_path=tmp_path / "threshold.db")
            try:
                assert db._slow_query_threshold_ms == 500
            finally:
                db.close()

    def test_query_logging_enabled_in_development(self, tmp_path: Path) -> None:
        """Should enable query logging in development mode."""
        with patch("src.utils.db_helpers.Config") as mock_config:
            mock_config.SLOW_QUERY_THRESHOLD_MS = 100
            mock_config.LOG_LEVEL = "INFO"
            mock_config.is_development.return_value = True

            from src.db.models import Database

            db = Database(db_path=tmp_path / "dev.db")
            try:
                assert db._should_log_queries is True
            finally:
                db.close()

    def test_query_logging_enabled_for_debug_level(self, tmp_path: Path) -> None:
        """Should enable query logging when LOG_LEVEL is DEBUG."""
        with patch("src.utils.db_helpers.Config") as mock_config:
            mock_config.SLOW_QUERY_THRESHOLD_MS = 100
            mock_config.LOG_LEVEL = "DEBUG"
            mock_config.is_development.return_value = False

            from src.db.models import Database

            db = Database(db_path=tmp_path / "debug.db")
            try:
                assert db._should_log_queries is True
            finally:
                db.close()

    def test_query_logging_disabled_in_production(self, tmp_path: Path) -> None:
        """Should disable query logging in production with non-DEBUG level."""
        with patch("src.utils.db_helpers.Config") as mock_config:
            mock_config.SLOW_QUERY_THRESHOLD_MS = 100
            mock_config.LOG_LEVEL = "INFO"
            mock_config.is_development.return_value = False

            from src.db.models import Database

            db = Database(db_path=tmp_path / "prod.db")
            try:
                assert db._should_log_queries is False
            finally:
                db.close()


# Import after patching environment
@pytest.fixture
def test_database(tmp_path: Path) -> Generator[Database]:
    """Create isolated test database for each test."""
    from src.db.models import Database

    db = Database(db_path=tmp_path / "test.db")
    yield db
    db.close()
