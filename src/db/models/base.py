"""Base database infrastructure.

Contains the core Database class with initialization and connection pooling.
The Database class is extended via mixins defined in other modules.
"""

import sqlite3
from pathlib import Path
from typing import Any

from yoyo import get_backend, read_migrations

from src.config import Config
from src.utils.connection_pool import ConnectionPool
from src.utils.db_helpers import execute_with_timing, init_query_logging
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Path to migrations directory
MIGRATIONS_DIR = Path(__file__).parent.parent.parent.parent / "migrations"


class DatabaseBase:
    """Base database class with core infrastructure.

    Provides connection pooling, query execution with timing, and migration support.
    Extended via mixins for specific entity operations.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or Config.DATABASE_PATH
        # Query logging is only active in development/debug mode
        self._should_log_queries, self._slow_query_threshold_ms = init_query_logging()
        # Use connection pool for efficient connection reuse
        self._pool = ConnectionPool(self.db_path)
        self._init_db()

    def close(self) -> None:
        """Close all connections in the pool.

        Call this on application shutdown.
        """
        self._pool.close_all()

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute a query with optional timing and logging.

        Delegates to shared execute_with_timing() helper.
        """
        return execute_with_timing(
            conn,
            query,
            params,
            should_log=self._should_log_queries,
            slow_query_threshold_ms=self._slow_query_threshold_ms,
        )

    def _init_db(self) -> None:
        """Run yoyo migrations to initialize/update the database schema."""
        logger.debug("Initializing database", extra={"db_path": str(self.db_path)})
        backend = get_backend(f"sqlite:///{self.db_path}")
        migrations = read_migrations(str(MIGRATIONS_DIR))
        try:
            with backend.lock():
                migrations_to_apply = backend.to_apply(migrations)
                if migrations_to_apply:
                    logger.info(
                        "Applying database migrations", extra={"count": len(migrations_to_apply)}
                    )
                backend.apply_migrations(migrations_to_apply)
        finally:
            backend.connection.close()
