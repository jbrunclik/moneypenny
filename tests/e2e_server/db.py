"""Databases: the migrated templates, a byte copy per test, and cleanup."""

import contextlib
import shutil
import threading
import time
from typing import Any
from unittest.mock import patch

from flask import Flask, g, request

from tests.e2e_server.context import DEFAULT_CONFIG, isolated_configs, set_thread_context
from tests.e2e_server.settings import (
    E2E_DB_DIR,
    E2E_PORT,
    TEMPLATE_BLOB_PATH,
    TEMPLATE_DB_PATH,
)


def cleanup_databases() -> None:
    """Remove all test database files (including template and test-specific files)."""
    # Clean up template files and all test-specific files
    patterns = [f"e2e-template-{E2E_PORT}*.db*", f"e2e-test-{E2E_PORT}-*.db*"]
    for pattern in patterns:
        for f in E2E_DB_DIR.glob(pattern):
            with contextlib.suppress(OSError):  # e.g. the file is still open
                f.unlink()


def create_templates() -> None:
    """Create template databases with all migrations applied (once at startup)."""
    from src.db.blob_store import BlobStore
    from src.db.models import Database

    print("Creating template databases...")
    Database(db_path=TEMPLATE_DB_PATH)
    BlobStore(db_path=TEMPLATE_BLOB_PATH)
    print(f"Template DB: {TEMPLATE_DB_PATH}")
    print(f"Template Blob: {TEMPLATE_BLOB_PATH}")


def apply_db_patches(stack: contextlib.ExitStack) -> None:
    """Skip per-context migration checks and fsyncs (test data is disposable)."""
    # Every per-test context is a byte copy of the template, so it never
    # needs a migration check. Yoyo's read_migrations + to_apply on each
    # Database() took 5-6s per context on a 2-vCPU CI runner (6ms on a
    # dev Mac) - CPU-bound Python holding the GIL, so every other in-flight
    # request stalled with it (SLOW phases: init=5.00, lock_wait=2.67).
    from src.db.models.base import DatabaseBase

    stack.enter_context(patch.object(DatabaseBase, "_init_db", lambda self: None))

    # Test data is disposable: don't fsync on every commit. The pragma is
    # per-connection, so wrap the pool's connection factory.
    from src.utils.connection_pool import ConnectionPool

    _orig_create = ConnectionPool._create_connection

    def _create_nosync(self: ConnectionPool) -> Any:
        conn = _orig_create(self)
        conn.execute("PRAGMA synchronous=OFF")
        return conn

    stack.enter_context(patch.object(ConnectionPool, "_create_connection", _create_nosync))


def register_db_resolver(app: Flask) -> None:
    """Give each X-Test-Execution-Id its own database, blob store and mock config."""
    from src.db.blob_store import BlobStore
    from src.db.models import Database

    # Map to store active DB connections: test_id -> (Database, BlobStore)
    active_contexts: dict[str, tuple[Database, BlobStore]] = {}
    active_contexts_lock = threading.Lock()

    @app.before_request
    def resolve_db():
        test_id = request.headers.get("X-Test-Execution-Id")

        # If no header (e.g. browser request without fixture), use default session
        if not test_id:
            test_id = "default-shared-session"

        # Existing contexts never touch the lock: a request for a live test
        # must not queue behind another worker's context creation.
        g._phases = {}
        ctx = active_contexts.get(test_id)
        if ctx is None:
            t0 = time.perf_counter()
            with active_contexts_lock:
                g._phases["lock_wait"] = time.perf_counter() - t0
                ctx = active_contexts.get(test_id)
                if ctx is None:
                    # Copy template databases for this test context (much faster than migrations)
                    safe_id = "".join(c for c in test_id if c.isalnum() or c in "-_")
                    db_path = E2E_DB_DIR / f"e2e-test-{E2E_PORT}-{safe_id}.db"
                    blob_path = E2E_DB_DIR / f"e2e-test-{E2E_PORT}-{safe_id}-blobs.db"
                    t1 = time.perf_counter()
                    shutil.copy2(TEMPLATE_DB_PATH, db_path)
                    shutil.copy2(TEMPLATE_BLOB_PATH, blob_path)
                    g._phases["copy"] = time.perf_counter() - t1
                    # Create Database/BlobStore instances (no migrations needed - schema is in the copy)
                    t2 = time.perf_counter()
                    db = Database(db_path=db_path)
                    blob_store = BlobStore(db_path=blob_path)
                    g._phases["init"] = time.perf_counter() - t2
                    ctx = (db, blob_store)
                    active_contexts[test_id] = ctx
                    isolated_configs.setdefault(test_id, DEFAULT_CONFIG.copy())
        g.db, g.blob_store = ctx
        isolated_configs.setdefault(test_id, DEFAULT_CONFIG.copy())
        g._phases["resolve_done"] = time.perf_counter() - g._req_start
        set_thread_context(g.db, g.blob_store, isolated_configs[test_id])
