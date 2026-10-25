"""SQLite storage for the `limits` library, shared by every worker process.

Flask-Limiter's `memory://` storage counts per process, so with several
gunicorn workers each limit is effectively multiplied by the worker count and
a reload resets it. This storage keeps fixed-window counters in a small SQLite
file of its own (never the main database, so rate-limit writes never wait on
its write lock).

Importing this module registers the `sqlite://` scheme; the file path comes
from the `path` storage option (Flask-Limiter's `storage_options`).

- Every increment is one `INSERT ... ON CONFLICT ... RETURNING` statement in
  autocommit mode, so concurrent workers never lose a hit.
- WAL mode and a short busy timeout keep readers and writers from blocking
  each other for long; a storage error surfaces as an exception that
  Flask-Limiter's in-memory fallback and `swallow_errors` turn into "fail open".
- Expired counters are reset on their next hit and swept lazily.
"""

import contextlib
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from limits.errors import ConfigurationError
from limits.storage import Storage

from src.utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# A counter write takes microseconds; waiting longer than this means the file
# is wedged, and failing open beats stalling the request
_BUSY_TIMEOUT_SECONDS = 1.0
# How often one process sweeps expired counters out of the table
_CLEANUP_INTERVAL_SECONDS = 60.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rate_limits (
    key TEXT PRIMARY KEY,
    count INTEGER NOT NULL,
    expires_at REAL NOT NULL
)
"""

# A counter whose window has expired restarts at `amount` with a new expiry
_INCR_SQL = """
INSERT INTO rate_limits (key, count, expires_at) VALUES (:key, :amount, :expires_at)
ON CONFLICT (key) DO UPDATE SET
    count = CASE WHEN expires_at <= :now THEN excluded.count ELSE count + excluded.count END,
    expires_at = CASE WHEN expires_at <= :now THEN excluded.expires_at ELSE expires_at END
RETURNING count
"""


def _now() -> float:
    """Epoch seconds; a seam so tests can move the clock without patching `time`."""
    return time.time()


class SQLiteStorage(Storage):
    """Fixed-window rate-limit counters in a SQLite file shared across processes."""

    STORAGE_SCHEME = ["sqlite"]  # noqa: RUF012  (type fixed by limits.storage.Storage)

    def __init__(
        self,
        uri: str | None = None,
        wrap_exceptions: bool = False,
        **options: float | str | bool,
    ) -> None:
        path = options.pop("path", None)
        if not path:
            raise ConfigurationError("sqlite:// rate-limit storage needs a `path` option")
        self.path = Path(str(path))
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._conn_pid: int | None = None
        self._last_cleanup = 0.0
        super().__init__(uri, wrap_exceptions=wrap_exceptions, **options)

    @property
    def base_exceptions(self) -> type[Exception] | tuple[type[Exception], ...]:
        return sqlite3.Error

    def _connect(self) -> sqlite3.Connection:
        # Connect lazily, and again after a fork: a connection must never be
        # shared between processes
        if self._conn is not None and self._conn_pid == os.getpid():
            return self._conn
        conn = sqlite3.connect(
            self.path,
            timeout=_BUSY_TIMEOUT_SECONDS,
            autocommit=True,
            check_same_thread=False,
        )
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(_SCHEMA)
        except sqlite3.Error:
            conn.close()
            raise
        self._conn = conn
        self._conn_pid = os.getpid()
        return conn

    def _run(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        """Run `operation` on the connection; log and re-raise storage errors."""
        with self._lock:
            try:
                return operation(self._connect())
            except sqlite3.Error as exc:
                logger.warning(
                    "Rate-limit storage error", extra={"error": str(exc), "path": str(self.path)}
                )
                self._close()
                raise

    def _close(self) -> None:
        if self._conn is not None and self._conn_pid == os.getpid():
            with contextlib.suppress(sqlite3.Error):
                self._conn.close()
        self._conn = None
        self._conn_pid = None

    def _maybe_cleanup(self, conn: sqlite3.Connection, now: float) -> None:
        if now - self._last_cleanup < _CLEANUP_INTERVAL_SECONDS:
            return
        self._last_cleanup = now
        conn.execute("DELETE FROM rate_limits WHERE expires_at <= ?", (now,))

    def incr(self, key: str, expiry: int, amount: int = 1) -> int:
        """Add `amount` to the counter, starting a new `expiry`-second window if needed."""

        def operation(conn: sqlite3.Connection) -> int:
            now = _now()
            self._maybe_cleanup(conn, now)
            params: dict[str, Any] = {
                "key": key,
                "amount": amount,
                "expires_at": now + expiry,
                "now": now,
            }
            # fetchall steps the statement to completion, which commits it
            rows = conn.execute(_INCR_SQL, params).fetchall()
            return int(rows[0][0])

        return self._run(operation)

    def get(self, key: str) -> int:
        """Current count in the live window (0 if none)."""

        def operation(conn: sqlite3.Connection) -> int:
            row = conn.execute(
                "SELECT count FROM rate_limits WHERE key = ? AND expires_at > ?",
                (key, _now()),
            ).fetchone()
            return int(row[0]) if row else 0

        return self._run(operation)

    def get_expiry(self, key: str) -> float:
        """Epoch seconds when the live window ends (now if there is none)."""

        def operation(conn: sqlite3.Connection) -> float:
            now = _now()
            row = conn.execute(
                "SELECT expires_at FROM rate_limits WHERE key = ? AND expires_at > ?",
                (key, now),
            ).fetchone()
            return float(row[0]) if row else now

        return self._run(operation)

    def check(self) -> bool:
        """Whether the database answers; never raises (Flask-Limiter polls it to recover)."""
        try:
            return self._run(lambda conn: conn.execute("SELECT 1").fetchone() is not None)
        except sqlite3.Error:
            return False

    def reset(self) -> int | None:
        """Drop every counter; returns how many were removed."""
        return self._run(lambda conn: conn.execute("DELETE FROM rate_limits").rowcount)

    def clear(self, key: str) -> None:
        """Drop one counter."""
        self._run(lambda conn: conn.execute("DELETE FROM rate_limits WHERE key = ?", (key,)))
