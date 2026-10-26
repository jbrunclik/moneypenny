"""Per-test isolation: mock config, database and blob store per X-Test-Execution-Id."""

import threading
from typing import Any

# Thread-local storage for context propagation
_thread_context = threading.local()
OriginalThread = threading.Thread


class ContextPropagatingThread(OriginalThread):
    """Thread that ensures the DB context is propagated to the child thread."""

    def __init__(self, *args, **kwargs):
        # Workaround for threading.Timer (and others) which inherit from Thread
        # but call Thread.__init__(self). Since we patched threading.Thread,
        # they end up calling THIS __init__.
        # If 'self' is not an instance of ContextPropagatingThread, just call original init.
        if not isinstance(self, ContextPropagatingThread):
            OriginalThread.__init__(self, *args, **kwargs)
            return

        super().__init__(*args, **kwargs)
        # Capture current context from parent thread
        self.captured_db = getattr(_thread_context, "db", None)
        self.captured_blob_store = getattr(_thread_context, "blob_store", None)
        self.captured_config = getattr(_thread_context, "config", None)

    def run(self):
        # Restore context in child thread
        if self.captured_db:
            _thread_context.db = self.captured_db
        if self.captured_blob_store:
            _thread_context.blob_store = self.captured_blob_store
        if self.captured_config:
            _thread_context.config = self.captured_config
        super().run()


def set_thread_context(db, blob_store, config):
    _thread_context.db = db
    _thread_context.blob_store = blob_store
    _thread_context.config = config


# Default configuration
DEFAULT_CONFIG = {
    "response_prefix": "This is a mock response to: ",
    "input_tokens": 100,
    "output_tokens": 50,
    "stream_delay_ms": 10,
    "batch_delay_ms": 0,
    "custom_response": None,
    # Canned grounding-check outcome ({"annotations", "summary"}); empty = no check
    "grounding_result": None,
    "emit_thinking": False,
    # Custom thinking text and a hold before the answer's tokens start
    "thinking_text": "Let me think about this...",
    "thinking_hold_ms": 0,
    # Hold the thinking until the test calls /test/release-thinking instead of
    # for a fixed time (a test acting on the live state is never raced by it)
    "thinking_until_released": False,
    "thinking_released": False,
    # Emit a transient-error "retry" status first and hold it this long (ms)
    "emit_retry_hold_ms": 0,
    # The next streamed turn fails before any text (one-shot) - the real
    # route's error path: an error event, the empty reply removed
    "fail_next_stream": False,
    # The streamed turn reads mid-run steering before its answer ends (the
    # real graph reads it between tool rounds); off, steering goes unread
    "consume_steering": False,
    # Deep research: offer args for the next streamed turn (one-shot) and the
    # fake pipeline's delay between scripted steps
    "deep_research_offer": None,
    "deep_research_step_ms": 150,
    # Artifact for the next streamed turn (one-shot): {title, html} creates one,
    # {html, update: true} adds a version to the conversation's last artifact
    "artifact_next": None,
    "last_artifact_id": None,
    "search_results": None,
    "search_total": 0,
    # Planner mock config
    "planner_todoist_connected": False,
    "planner_calendar_connected": False,
    "planner_dashboard": None,  # Custom dashboard data
    # Garmin mock config
    "garmin_connected": False,
    "garmin_needs_reconnect": False,
    # Agents mock config
    "agents_command_center": None,  # Custom command center data
    # fnmatch patterns of /static/assets files that answer 404, as if a
    # deploy had deleted them (a page older than the build asks for them)
    "missing_assets": (),
}

# Global storage for isolated configs
isolated_configs = {}


class ContextAwareConfig:
    """A dict-like object that returns configuration isolated by X-Test-Execution-Id."""

    def _get_current(self) -> dict[str, Any]:
        # Check thread context first (populated by resolve_db)
        if hasattr(_thread_context, "config") and _thread_context.config:
            return _thread_context.config

        from flask import has_request_context, request

        if not has_request_context():
            return DEFAULT_CONFIG

        test_id = request.headers.get("X-Test-Execution-Id")
        if not test_id:
            return DEFAULT_CONFIG

        if test_id not in isolated_configs:
            # Initialize with a copy of defaults
            isolated_configs[test_id] = DEFAULT_CONFIG.copy()

        return isolated_configs[test_id]

    def __getitem__(self, key: str) -> Any:
        return self._get_current()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._get_current()[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._get_current().get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self._get_current()

    def copy(self) -> dict[str, Any]:
        return self._get_current().copy()


# Replace global dict with proxy
MOCK_CONFIG = ContextAwareConfig()


class ProxyDatabase:
    """Proxy that delegates to a thread-local Database instance based on request header."""

    def __getattr__(self, name: str) -> Any:
        if hasattr(_thread_context, "db"):
            return getattr(_thread_context.db, name)

        from flask import g, has_request_context

        if has_request_context() and hasattr(g, "db"):
            return getattr(g.db, name)

        # Detail error about context
        thread_name = threading.current_thread().name
        raise RuntimeError(f"Database accessed outside of request context. Thread: {thread_name}")


class ProxyBlobStore:
    """Proxy that delegates to a thread-local BlobStore instance based on request header."""

    def __getattr__(self, name: str) -> Any:
        if hasattr(_thread_context, "blob_store"):
            return getattr(_thread_context.blob_store, name)

        from flask import g, has_request_context

        if has_request_context() and hasattr(g, "blob_store"):
            return getattr(g.blob_store, name)

        raise RuntimeError(
            "BlobStore accessed outside of request context or without X-Test-Execution-Id"
        )
