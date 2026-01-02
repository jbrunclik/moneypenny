"""Database helper utilities.

This module provides shared utilities for database operations, used by both
the main database (models.py) and blob storage (blob_store.py).
"""

import sqlite3
import time
from typing import Any

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Default limits for log message truncation
QUERY_SNIPPET_MAX_LENGTH = 200
PARAMS_SNIPPET_MAX_LENGTH = 100


def execute_with_timing(
    conn: sqlite3.Connection,
    query: str,
    params: tuple[Any, ...] = (),
    *,
    should_log: bool,
    slow_query_threshold_ms: float,
    log_prefix: str = "",
) -> sqlite3.Cursor:
    """Execute a query with optional timing and logging.

    In development/debug mode, this function tracks query execution time
    and logs warnings for slow queries.

    Args:
        conn: SQLite connection
        query: SQL query string
        params: Query parameters
        should_log: Whether to enable timing and logging
        slow_query_threshold_ms: Threshold in ms for slow query warnings
        log_prefix: Optional prefix for log messages (e.g., "Blob " for blob store)

    Returns:
        SQLite cursor with results
    """
    if not should_log:
        return conn.execute(query, params)

    start_time = time.perf_counter()
    cursor = conn.execute(query, params)
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    # Truncate query for logging (normalize whitespace)
    query_snippet = " ".join(query.split())
    if len(query_snippet) > QUERY_SNIPPET_MAX_LENGTH:
        query_snippet = query_snippet[:QUERY_SNIPPET_MAX_LENGTH] + "..."

    # Truncate params for logging (avoid logging large data like base64 files)
    params_str = str(params)
    if len(params_str) > PARAMS_SNIPPET_MAX_LENGTH:
        params_snippet = params_str[:PARAMS_SNIPPET_MAX_LENGTH] + "..."
    else:
        params_snippet = params_str

    if elapsed_ms >= slow_query_threshold_ms:
        logger.warning(
            f"Slow {log_prefix}query detected",
            extra={
                "query_snippet": query_snippet,
                "params_snippet": params_snippet,
                "elapsed_ms": round(elapsed_ms, 2),
                "threshold_ms": slow_query_threshold_ms,
            },
        )
    elif Config.LOG_LEVEL == "DEBUG":
        logger.debug(
            f"{log_prefix}Query executed",
            extra={
                "query_snippet": query_snippet,
                "elapsed_ms": round(elapsed_ms, 2),
            },
        )

    return cursor


def init_query_logging() -> tuple[bool, float]:
    """Get query logging configuration from Config.

    Returns:
        Tuple of (should_log_queries, slow_query_threshold_ms)
    """
    should_log = Config.LOG_LEVEL == "DEBUG" or Config.is_development()
    threshold = Config.SLOW_QUERY_THRESHOLD_MS
    return should_log, threshold
