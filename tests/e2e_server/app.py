"""Assemble and run the E2E server: the real app with every external service mocked."""

import atexit
import contextlib
import os
import signal
import sys
from typing import Any, cast
from unittest.mock import patch

from tests.e2e_server.context import ContextPropagatingThread, ProxyBlobStore, ProxyDatabase
from tests.e2e_server.control_routes import test_bp
from tests.e2e_server.db import (
    apply_db_patches,
    cleanup_databases,
    create_templates,
    register_db_resolver,
)
from tests.e2e_server.fixture_routes import fixtures_bp
from tests.e2e_server.intercepts import register_intercepts
from tests.e2e_server.patches import apply_service_patches
from tests.e2e_server.request_log import register_request_log
from tests.e2e_server.settings import E2E_PID_FILE, E2E_PORT


def cleanup_pid_file() -> None:
    """Remove PID file on exit."""
    if E2E_PID_FILE.exists():
        with contextlib.suppress(Exception):
            E2E_PID_FILE.unlink()


def signal_handler(signum: int, frame: Any) -> None:
    """Handle signals and cleanup PID file."""
    cleanup_pid_file()
    cleanup_databases()
    sys.exit(0)


def main() -> None:
    """Start the E2E test server with all mocks applied."""
    # Write PID file
    try:
        E2E_PID_FILE.write_text(str(os.getpid()))
        atexit.register(cleanup_pid_file)
        atexit.register(cleanup_databases)
        # Also register signal handlers for cleanup
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
    except Exception as e:  # noqa: BLE001 - the server runs without a PID file
        print(f"Warning: Could not write PID file: {e}")

    print("E2E Test Server starting...")
    # Clean up any existing test databases
    cleanup_databases()

    # Use ExitStack to avoid deep nesting of context managers
    with contextlib.ExitStack() as stack:
        apply_service_patches(stack)

        # Import app after mocks are in place
        from src.app import create_app
        from src.db import blob_store as blob_store_module
        from src.db.models import Database, use_database

        create_templates()
        apply_db_patches(stack)

        # Create proxies for test isolation
        proxy_db = ProxyDatabase()
        proxy_blob_store = ProxyBlobStore()

        # One swap reaches every module that imported the global db
        stack.enter_context(use_database(cast(Database, proxy_db)))

        # Patch threading.Thread to propagate context (used in chat_streaming helper)
        stack.enter_context(
            patch("src.api.helpers.chat_streaming.threading.Thread", ContextPropagatingThread)
        )

        # get_blob_store() reads this global, so every caller sees the proxy
        stack.enter_context(blob_store_module._blob_store.override(proxy_blob_store))  # type: ignore[arg-type]

        app = create_app(apply_migrations=False)  # the templates are migrated
        app.config["TESTING"] = True

        from flask import request

        @app.after_request
        def _allow_test_header_on_assets(response):  # type: ignore[no-untyped-def]
            # Playwright adds X-Test-Execution-Id to every request, which turns
            # the opaque artifact frame's CORS asset fetches into preflights
            # (production sends no custom header, so no preflight happens)
            if request.path.startswith("/static/assets/"):
                response.headers["Access-Control-Allow-Headers"] = "X-Test-Execution-Id"
            return response

        # Hook order matters: the request clock starts before resolve_db,
        # which runs before the intercepts read the per-test mock config
        register_request_log(app)
        register_db_resolver(app)
        app.register_blueprint(test_bp)
        app.register_blueprint(fixtures_bp)
        register_intercepts(app)

        print(f"Starting E2E test server on http://localhost:{E2E_PORT}")
        print("Press Ctrl+C to stop")

        app.run(host="0.0.0.0", port=E2E_PORT, debug=False, threaded=True)
