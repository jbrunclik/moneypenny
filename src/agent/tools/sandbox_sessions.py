"""Per-conversation Docker sandbox session pool.

execute_code used to create and tear down a container per call (~1-2s startup
each time). Reusing a per-conversation session makes repeated executions fast
and gives code a persistent filesystem (/work) across calls. Each run() is
still a fresh Python process - variables do NOT persist, files do.

Mirrors the browser.py session pattern: LRU cap + TTL + background cleanup.
Pools are per-gunicorn-worker by design (a conversation may hit a different
worker and get a fresh session - correctness never depends on reuse).
"""

import atexit
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

_CLEANUP_INTERVAL_SECONDS = 60


@dataclass
class _Entry:
    session: Any
    last_used: float
    lock: threading.Lock = field(default_factory=threading.Lock)


class SandboxSessionPool:
    """LRU + TTL pool of open sandbox sessions keyed by conversation id."""

    def __init__(
        self,
        factory: Callable[[], Any],
        max_sessions: int,
        ttl_seconds: float,
    ) -> None:
        self._factory = factory
        self._max_sessions = max_sessions
        self._ttl_seconds = ttl_seconds
        self._entries: dict[str, _Entry] = {}
        self._pool_lock = threading.Lock()

    def _open_session(self) -> Any:
        session = self._factory()
        session.open()
        return session

    def _close_quietly(self, session: Any) -> None:
        try:
            session.close()
        except Exception:
            logger.warning("Failed to close sandbox session", exc_info=True)

    @contextmanager
    def session(self, key: str | None) -> Iterator[Any]:
        """Yield a session for `key`; None means ephemeral (open/close per call).

        A raise inside the with-block marks the pooled session broken: it is
        closed and removed so the next call gets a fresh one.
        """
        if key is None:
            session = self._open_session()
            try:
                yield session
            finally:
                self._close_quietly(session)
            return

        with self._pool_lock:
            entry = self._entries.pop(key, None)
            if entry is None:
                entry = _Entry(session=self._open_session(), last_used=time.monotonic())
            self._entries[key] = entry  # re-insert = move to MRU position
            self._evict_over_capacity_locked()

        with entry.lock:  # serialize runs against one container
            try:
                yield entry.session
                entry.last_used = time.monotonic()
            except Exception:
                with self._pool_lock:
                    if self._entries.get(key) is entry:
                        del self._entries[key]
                self._close_quietly(entry.session)
                raise

    def _evict_over_capacity_locked(self) -> None:
        """Close least-recently-used entries beyond capacity (callers hold the lock)."""
        while len(self._entries) > self._max_sessions:
            oldest_key = next(iter(self._entries))
            entry = self._entries.pop(oldest_key)
            logger.info("Evicting sandbox session (LRU)", extra={"key": oldest_key})
            self._close_quietly(entry.session)

    def cleanup_expired(self) -> int:
        """Close sessions idle past the TTL; returns how many were closed."""
        now = time.monotonic()
        with self._pool_lock:
            expired = [
                key
                for key, entry in self._entries.items()
                if now - entry.last_used > self._ttl_seconds
            ]
            entries = [self._entries.pop(key) for key in expired]
        for entry in entries:
            self._close_quietly(entry.session)
        if entries:
            logger.info("Cleaned up expired sandbox sessions", extra={"count": len(entries)})
        return len(entries)

    def close_all(self) -> None:
        with self._pool_lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for entry in entries:
            self._close_quietly(entry.session)


# ============ Module Singleton ============

_pool: SandboxSessionPool | None = None
_pool_init_lock = threading.Lock()


def _make_docker_session() -> Any:
    """Factory for real Docker sandbox sessions (shared settings with execute_code)."""
    from llm_sandbox import SandboxSession

    from src.agent.tools.code_execution import _SANDBOX_SESSION_KWARGS, _sandbox_runtime_configs

    return SandboxSession(
        image=Config.CODE_SANDBOX_IMAGE,
        runtime_configs=_sandbox_runtime_configs(),
        **_SANDBOX_SESSION_KWARGS,
    )


def _cleanup_loop(pool: SandboxSessionPool) -> None:
    while True:
        time.sleep(_CLEANUP_INTERVAL_SECONDS)
        try:
            pool.cleanup_expired()
        except Exception:
            logger.warning("Sandbox session cleanup failed", exc_info=True)


def get_sandbox_pool() -> SandboxSessionPool:
    """Get the process-wide sandbox session pool (double-checked locking)."""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_init_lock:
        if _pool is None:
            pool = SandboxSessionPool(
                factory=_make_docker_session,
                max_sessions=Config.CODE_SANDBOX_MAX_SESSIONS,
                ttl_seconds=Config.CODE_SANDBOX_SESSION_TTL_SECONDS,
            )
            thread = threading.Thread(
                target=_cleanup_loop, args=(pool,), daemon=True, name="sandbox-session-cleanup"
            )
            thread.start()
            atexit.register(pool.close_all)
            _pool = pool
    return _pool
