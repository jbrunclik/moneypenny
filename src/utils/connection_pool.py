"""Thread-local SQLite connection management.

SQLite works best with one connection per thread. This module provides a thread-local
connection pool that reuses connections within each thread, avoiding the overhead
of repeatedly opening and closing connections.

Usage:
    pool = ConnectionPool("/path/to/database.db")

    # Get a connection (reuses existing thread-local connection)
    with pool.get_connection() as conn:
        conn.execute("SELECT * FROM users")

    # Connections are automatically returned to the pool (not closed)
    # Call pool.close_all() on shutdown to close all connections
"""

import sqlite3
import threading
import weakref
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from src.utils.logging import get_logger

logger = get_logger(__name__)


class ConnectionPool:
    """Thread-local SQLite connection pool.

    Each thread gets its own connection that's reused for all operations.
    This is optimal for SQLite because:
    - SQLite uses file-level locking, so connection pools don't help concurrency
    - Reusing connections avoids open/close overhead
    - Thread-local connections avoid thread-safety issues
    """

    def __init__(self, db_path: Path | str, check_same_thread: bool = False) -> None:
        """Initialize the connection pool.

        Args:
            db_path: Path to the SQLite database file
            check_same_thread: If True, connections can only be used in the thread
                that created them (SQLite default). Set to False for multi-threaded
                use with proper synchronization.
        """
        self.db_path = Path(db_path) if isinstance(db_path, str) else db_path
        self.check_same_thread = check_same_thread
        self._local = threading.local()
        self._lock = threading.Lock()
        # Track all connections for cleanup
        self._connections: dict[int, sqlite3.Connection] = {}
        logger.debug(
            "Connection pool created",
            extra={"db_path": str(self.db_path)},
        )

    @staticmethod
    def _release_connection(
        lock: threading.Lock,
        connections: dict[int, sqlite3.Connection],
        thread_id: int,
    ) -> None:
        """Release a connection when its owning thread is garbage-collected.

        This is called by weakref.finalize when the Thread object is GC'd,
        providing automatic cleanup for short-lived threads. Uses only the
        arguments passed at registration time (no reference to self, which
        would prevent GC of the pool itself).
        """
        with lock:
            conn = connections.pop(thread_id, None)
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    def _reap_dead_threads(self) -> None:
        """Close connections for threads that no longer exist.

        Must be called with self._lock held. Acts as a fallback for cases
        where weakref.finalize hasn't fired yet (e.g. Thread objects still
        referenced elsewhere).
        """
        alive_thread_ids = {t.ident for t in threading.enumerate()}
        dead_thread_ids = [tid for tid in self._connections if tid not in alive_thread_ids]
        for tid in dead_thread_ids:
            conn = self._connections.pop(tid)
            try:
                conn.close()
            except sqlite3.Error:
                pass
        if dead_thread_ids:
            logger.debug(
                "Reaped dead thread connections",
                extra={
                    "dead_count": len(dead_thread_ids),
                    "remaining": len(self._connections),
                },
            )

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new connection with standard settings."""
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=self.check_same_thread,
            # Timeout for waiting on locks (default is 5 seconds)
            timeout=30.0,
        )
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrent read/write performance
        conn.execute("PRAGMA journal_mode=WAL")
        # Note: Foreign keys are intentionally NOT enabled because the app
        # preserves message_costs after message/conversation deletion
        # (for cost reporting - the money was already spent)
        return conn

    def _get_thread_connection(self) -> sqlite3.Connection:
        """Get or create a connection for the current thread."""
        thread_id = threading.get_ident()

        # Check if this thread already has a connection
        conn: sqlite3.Connection | None = getattr(self._local, "connection", None)

        if conn is not None:
            # Verify the connection is still valid
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.Error:
                # Connection is broken, remove it
                logger.warning(
                    "Thread connection was broken, creating new one",
                    extra={"thread_id": thread_id, "db_path": str(self.db_path)},
                )
                with self._lock:
                    self._connections.pop(thread_id, None)
                conn = None

        # Create a new connection for this thread
        conn = self._create_connection()
        self._local.connection = conn

        with self._lock:
            # Reap connections from threads that have exited before adding new one
            self._reap_dead_threads()
            self._connections[thread_id] = conn

        # Register a weak-reference callback so the connection is automatically
        # closed when the Thread object is garbage-collected (i.e. after the
        # thread exits and nothing else holds a reference to it).
        current_thread = threading.current_thread()
        weakref.finalize(
            current_thread,
            ConnectionPool._release_connection,
            self._lock,
            self._connections,
            thread_id,
        )

        logger.debug(
            "Created new thread connection",
            extra={
                "thread_id": thread_id,
                "db_path": str(self.db_path),
                "total_connections": len(self._connections),
            },
        )
        return conn

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection]:
        """Get a connection for the current thread.

        The connection is reused for all operations in this thread.
        It is NOT closed when the context manager exits - only returned
        to the pool for reuse.

        Yields:
            A SQLite connection configured with row_factory=sqlite3.Row
        """
        conn = self._get_thread_connection()
        try:
            yield conn
        except Exception:
            # On error, rollback any uncommitted transaction
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            raise

    def close_thread_connection(self) -> None:
        """Close the connection for the current thread.

        Call this when a thread is about to exit to free resources.
        """
        thread_id = threading.get_ident()
        conn = getattr(self._local, "connection", None)

        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
            self._local.connection = None

            with self._lock:
                self._connections.pop(thread_id, None)

            logger.debug(
                "Closed thread connection",
                extra={"thread_id": thread_id, "db_path": str(self.db_path)},
            )

    def close_all(self) -> None:
        """Close all connections in the pool.

        Call this on application shutdown.
        """
        with self._lock:
            for _thread_id, conn in list(self._connections.items()):
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
            self._connections.clear()

        # Also clear the thread-local storage for the current thread
        if hasattr(self._local, "connection"):
            self._local.connection = None

        logger.info(
            "All pool connections closed",
            extra={"db_path": str(self.db_path)},
        )

    def connection_count(self) -> int:
        """Return the number of active connections in the pool."""
        with self._lock:
            return len(self._connections)

    def execute(self, query: str, params: tuple[object, ...] = ()) -> sqlite3.Cursor:
        """Execute a query using a pooled connection.

        Convenience method for simple queries.

        Args:
            query: SQL query string
            params: Query parameters

        Returns:
            Cursor with results
        """
        with self.get_connection() as conn:
            return conn.execute(query, params)
