#!/usr/bin/env python3
"""E2E test server with mocked external services.

This server runs Flask with all external dependencies mocked (LLM, search, etc.).
Playwright auto-starts this server via webServer config.

Usage:
    python tests/e2e-server.py
"""

import atexit
import base64
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set test environment BEFORE importing app modules
# Use "testing" for FLASK_ENV (enables testing-specific behavior)
# Use E2E_TESTING=true to bypass auth (separate from unit tests which need auth)
os.environ["FLASK_ENV"] = "testing"
os.environ["E2E_TESTING"] = "true"  # Enable auth bypass for E2E tests
os.environ["GEMINI_API_KEY"] = "test-api-key-for-e2e"
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-e2e-testing"
os.environ["ALLOWED_EMAILS"] = "*"  # Allow all emails in E2E tests
os.environ["LOG_LEVEL"] = "WARNING"  # Reduce noise during E2E tests
os.environ["RATE_LIMITING_ENABLED"] = "false"  # Disable rate limiting for parallel tests

# Template databases are created once at startup with migrations applied
# Test contexts copy the template instead of running migrations for each test
TEMPLATE_DB_PATH = PROJECT_ROOT / "tests" / "e2e-template.db"
TEMPLATE_BLOB_PATH = PROJECT_ROOT / "tests" / "e2e-template-blobs.db"
# Set env vars to the template path - migrations will run on template
os.environ["DATABASE_PATH"] = str(TEMPLATE_DB_PATH)
os.environ["BLOB_STORAGE_PATH"] = str(TEMPLATE_BLOB_PATH)

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


# PID file for cleanup
E2E_PID_FILE = PROJECT_ROOT / ".e2e-server.pid"


# Default configuration
DEFAULT_CONFIG = {
    "response_prefix": "This is a mock response to: ",
    "input_tokens": 100,
    "output_tokens": 50,
    "stream_delay_ms": 10,
    "batch_delay_ms": 0,
    "custom_response": None,
    "emit_thinking": False,
    "search_results": None,
    "search_total": 0,
    # Planner mock config
    "planner_todoist_connected": False,
    "planner_calendar_connected": False,
    "planner_dashboard": None,  # Custom dashboard data
    # Agents mock config
    "agents_command_center": None,  # Custom command center data
}

# Global storage for isolated configs
_isolated_configs = {}


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

        if test_id not in _isolated_configs:
            # Initialize with a copy of defaults
            _isolated_configs[test_id] = DEFAULT_CONFIG.copy()

        return _isolated_configs[test_id]

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


def create_mock_llm() -> MagicMock:
    """Create mock LLM that returns proper AIMessage objects.

    The mock returns a proper AIMessage object that LangGraph can process,
    rather than a MagicMock which causes "Unsupported message type" errors.
    """
    from langchain_core.messages import AIMessage

    mock = MagicMock()
    mock_instance = MagicMock()

    def mock_invoke(messages: list[Any], **kwargs: Any) -> AIMessage:
        # Apply batch delay if configured (for testing conversation switching)
        batch_delay_ms = MOCK_CONFIG.get("batch_delay_ms", 0)
        if batch_delay_ms > 0:
            time.sleep(batch_delay_ms / 1000)

        # Extract user message from the last message
        user_message = ""
        if messages:
            last_msg = messages[-1]
            if hasattr(last_msg, "content"):
                content = last_msg.content
                if isinstance(content, str):
                    user_message = content
                elif isinstance(content, list):
                    # Extract text from multimodal content
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            user_message = part.get("text", "")
                            break

        # Use custom response if set, otherwise use prefix + message
        if MOCK_CONFIG["custom_response"]:
            response_text = MOCK_CONFIG["custom_response"]
        else:
            prefix = MOCK_CONFIG["response_prefix"]
            response_text = f"{prefix}{user_message[:100]}"

        # Return a proper AIMessage that LangGraph can process
        input_tokens = MOCK_CONFIG["input_tokens"]
        output_tokens = MOCK_CONFIG["output_tokens"]
        return AIMessage(
            content=response_text,
            usage_metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        )

    mock_instance.invoke = mock_invoke
    # Ensure bind_tools returns the same instance so tool binding works
    mock_instance.bind_tools = MagicMock(return_value=mock_instance)
    mock.return_value = mock_instance
    return mock


def create_mock_ddgs() -> MagicMock:
    """Create mock DuckDuckGo search."""
    mock = MagicMock()
    mock_instance = MagicMock()
    mock_instance.__enter__ = MagicMock(return_value=mock_instance)
    mock_instance.__exit__ = MagicMock(return_value=False)

    def mock_text(*args: Any, **kwargs: Any) -> list[dict[str, str]]:
        return [
            {
                "title": "Example Search Result",
                "href": "https://example.com/result",
                "body": "This is a mock search result snippet.",
            }
        ]

    mock_instance.text = mock_text
    mock.return_value = mock_instance
    return mock


def create_mock_httpx() -> MagicMock:
    """Create mock httpx for URL fetching."""
    mock = MagicMock()
    mock_instance = MagicMock()
    mock_instance.__enter__ = MagicMock(return_value=mock_instance)
    mock_instance.__exit__ = MagicMock(return_value=False)

    def mock_get(url: str, **kwargs: Any) -> MagicMock:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body><h1>Mock Page</h1><p>Mock content.</p></body></html>"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()
        return mock_response

    mock_instance.get = mock_get
    mock.return_value = mock_instance
    return mock


def create_mock_genai() -> MagicMock:
    """Create mock Gemini image generation."""
    mock = MagicMock()
    mock_instance = MagicMock()

    # Minimal valid 1x1 red PNG
    png_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )

    def mock_generate_content(*args: Any, **kwargs: Any) -> MagicMock:
        mock_response = MagicMock()
        mock_response.candidates = [MagicMock()]
        mock_response.candidates[0].content.parts = [MagicMock()]
        mock_response.candidates[0].content.parts[0].inline_data.data = png_data
        mock_response.candidates[0].content.parts[0].inline_data.mime_type = "image/png"

        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 50
        mock_response.usage_metadata.candidates_token_count = 0
        mock_response.usage_metadata.thoughts_token_count = 0

        return mock_response

    mock_instance.models.generate_content = mock_generate_content
    mock.return_value = mock_instance
    return mock


def create_mock_google_tokeninfo() -> MagicMock:
    """Create mock Google token validation."""
    mock = MagicMock()

    def mock_get(url: str, **kwargs: Any) -> MagicMock:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "aud": "test-client-id",
            "email": "test@example.com",
            "name": "Test User",
            "picture": "https://example.com/pic.jpg",
            "email_verified": "true",
        }
        return mock_response

    mock.side_effect = mock_get
    return mock


def create_mock_stream_chat() -> Any:
    """Create a mock stream_chat method that yields tokens properly.

    The default LLM mock doesn't support LangGraph's stream mode, so we need
    to mock the stream_chat method to yield individual tokens followed by the
    final result tuple.
    """
    from collections.abc import Generator

    def mock_stream_chat(
        self: Any,
        message: str,
        files: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        force_tools: list[str] | None = None,
        user_name: str | None = None,
        user_id: str | None = None,
    ) -> Generator[str | tuple[str, dict[str, Any], list[dict[str, Any]], dict[str, Any]]]:
        """Mock streaming that yields tokens word-by-word."""
        # Use custom response if set, otherwise use prefix + message
        if MOCK_CONFIG["custom_response"]:
            response_text = MOCK_CONFIG["custom_response"]
        else:
            prefix = MOCK_CONFIG["response_prefix"]
            response_text = f"{prefix}{message[:100]}"

        # Stream tokens word-by-word (simulates real LLM streaming)
        words = response_text.split()
        delay_s = MOCK_CONFIG["stream_delay_ms"] / 1000

        for i, word in enumerate(words):
            # Add space before word (except first)
            token = f" {word}" if i > 0 else word
            yield token
            time.sleep(delay_s)

        # Yield final tuple: (clean_content, metadata, tool_results, usage_info)
        # The real stream_chat yields this at the end
        input_tokens = MOCK_CONFIG["input_tokens"]
        output_tokens = MOCK_CONFIG["output_tokens"]
        usage_info = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        yield (response_text, {}, [], usage_info)

    return mock_stream_chat


def create_mock_stream_chat_events() -> Any:
    """Create a mock stream_chat_events method that yields structured events.

    This method yields events including thinking, tool_start, tool_end, token, and final.
    """
    from collections.abc import Generator

    def mock_stream_chat_events(
        self: Any,
        message: str,
        files: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        force_tools: list[str] | None = None,
        user_name: str | None = None,
        user_id: str | None = None,
        custom_instructions: str | None = None,
        is_planning: bool = False,
        dashboard_data: dict[str, Any] | None = None,
    ) -> Generator[dict[str, Any]]:
        """Mock streaming that yields structured events."""
        # Use custom response if set, otherwise use prefix + message
        if MOCK_CONFIG["custom_response"]:
            response_text = MOCK_CONFIG["custom_response"]
        else:
            prefix = MOCK_CONFIG["response_prefix"]
            response_text = f"{prefix}{message[:100]}"

        delay_s = MOCK_CONFIG["stream_delay_ms"] / 1000

        # Optionally yield a thinking event (based on mock config or message content)
        if "think" in message.lower() or MOCK_CONFIG.get("emit_thinking"):
            time.sleep(delay_s)
            yield {"type": "thinking", "text": "Let me think about this..."}

        # Optionally yield tool events (if force_tools specified)
        if force_tools:
            for tool in force_tools:
                time.sleep(delay_s)
                yield {"type": "tool_start", "tool": tool}
                time.sleep(delay_s * 2)  # Simulate tool execution
                yield {"type": "tool_end", "tool": tool}

        # Stream tokens word-by-word
        words = response_text.split()
        for i, word in enumerate(words):
            # Add space before word (except first)
            token = f" {word}" if i > 0 else word
            yield {"type": "token", "text": token}
            time.sleep(delay_s)

        # Yield final event
        input_tokens = MOCK_CONFIG["input_tokens"]
        output_tokens = MOCK_CONFIG["output_tokens"]
        usage_info = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        yield {
            "type": "final",
            "content": response_text,
            "metadata": {},
            "tool_results": [],
            "usage_info": usage_info,
        }

    return mock_stream_chat_events


def cleanup_pid_file() -> None:
    """Remove PID file on exit."""
    if E2E_PID_FILE.exists():
        try:
            E2E_PID_FILE.unlink()
        except Exception:
            pass


def cleanup_databases() -> None:
    """Remove all test database files (including template and test-specific files)."""
    # Clean up template files and all test-specific files
    patterns = ["e2e-template*.db*", "e2e-test-*.db*"]
    for pattern in patterns:
        for f in PROJECT_ROOT.glob(f"tests/{pattern}"):
            try:
                f.unlink()
            except Exception:
                pass  # Ignore errors (e.g. if file is still open)


def signal_handler(signum: int, frame: Any) -> None:
    """Handle signals and cleanup PID file."""
    cleanup_pid_file()
    cleanup_databases()
    sys.exit(0)


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


def main() -> None:
    """Start the E2E test server with all mocks applied."""
    import contextlib

    # Write PID file
    try:
        E2E_PID_FILE.write_text(str(os.getpid()))
        atexit.register(cleanup_pid_file)
        atexit.register(cleanup_databases)
        # Also register signal handlers for cleanup
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
    except Exception as e:
        print(f"Warning: Could not write PID file: {e}")

    import shutil

    print("E2E Test Server starting...")
    # Clean up any existing test databases
    cleanup_databases()

    # Use ExitStack to avoid deep nesting of context managers
    with contextlib.ExitStack() as stack:
        # Apply external service mocks
        stack.enter_context(patch("src.agent.graph.ChatGoogleGenerativeAI", create_mock_llm()))
        stack.enter_context(patch("src.agent.agent.ChatGoogleGenerativeAI", create_mock_llm()))
        stack.enter_context(patch("src.agent.tools.web.DDGS", create_mock_ddgs()))
        stack.enter_context(patch("src.agent.tools.web.httpx.Client", create_mock_httpx()))
        stack.enter_context(
            patch("src.agent.tools.image_generation.genai.Client", create_mock_genai())
        )
        stack.enter_context(
            patch("src.auth.google_auth.requests.get", create_mock_google_tokeninfo())
        )
        stack.enter_context(
            patch("src.agent.agent.ChatAgent.stream_chat", create_mock_stream_chat())
        )
        stack.enter_context(
            patch(
                "src.agent.agent.ChatAgent.stream_chat_events",
                create_mock_stream_chat_events(),
            )
        )

        # Import app after mocks are in place
        from src.app import create_app
        from src.db.blob_store import BlobStore
        from src.db.models import Database

        # Create template databases with all migrations applied (once at startup)
        print("Creating template databases...")
        Database(db_path=TEMPLATE_DB_PATH)
        BlobStore(db_path=TEMPLATE_BLOB_PATH)
        print(f"Template DB: {TEMPLATE_DB_PATH}")
        print(f"Template Blob: {TEMPLATE_BLOB_PATH}")

        # Create proxies for test isolation
        proxy_db = ProxyDatabase()
        proxy_blob_store = ProxyBlobStore()

        # Patch database everywhere with proxy
        stack.enter_context(patch("src.db.models.db", proxy_db))
        stack.enter_context(patch("src.auth.jwt_auth.db", proxy_db))
        stack.enter_context(patch("src.api.routes.db", proxy_db))
        stack.enter_context(patch("src.agent.prompts.db", proxy_db))

        # Patch database in all route modules (routes are split across multiple files)
        route_modules = [
            "auth",
            "calendar",
            "chat",
            "conversations",
            "costs",
            "files",
            "memory",
            "planner",
            "settings",
            "todoist",
        ]
        for module in route_modules:
            stack.enter_context(patch(f"src.api.routes.{module}.db", proxy_db))

        # Patch database in helper modules and utilities
        stack.enter_context(patch("src.api.helpers.chat_streaming.db", proxy_db))
        stack.enter_context(patch("src.api.helpers.validation.db", proxy_db))
        stack.enter_context(patch("src.api.utils.db", proxy_db))

        # Patch threading.Thread to propagate context (used in chat_streaming helper)
        stack.enter_context(
            patch("src.api.helpers.chat_streaming.threading.Thread", ContextPropagatingThread)
        )

        # Patch blob store everywhere with proxy
        stack.enter_context(patch("src.db.blob_store._blob_store", proxy_blob_store))
        stack.enter_context(
            patch("src.db.models.helpers.get_blob_store", return_value=proxy_blob_store)
        )
        stack.enter_context(
            patch("src.db.models.message.get_blob_store", return_value=proxy_blob_store)
        )
        stack.enter_context(patch("src.api.routes.get_blob_store", return_value=proxy_blob_store))

        app = create_app()
        app.config["TESTING"] = True

        # Import Flask globals for use in before_request and routes
        from flask import g, request

        # Map to store active DB connections: test_id -> (Database, BlobStore)
        active_contexts: dict[str, tuple[Database, BlobStore]] = {}
        active_contexts_lock = threading.Lock()

        @app.before_request
        def resolve_db():
            test_id = request.headers.get("X-Test-Execution-Id")

            # If no header (e.g. browser request without fixture), use default session
            if not test_id:
                test_id = "default-shared-session"

            # Thread-safe creation of test context
            with active_contexts_lock:
                if test_id not in active_contexts:
                    # Copy template databases for this test context (much faster than migrations)
                    safe_id = "".join(c for c in test_id if c.isalnum() or c in "-_")
                    db_path = PROJECT_ROOT / "tests" / f"e2e-test-{safe_id}.db"
                    blob_path = PROJECT_ROOT / "tests" / f"e2e-test-{safe_id}-blobs.db"

                    # Copy the template files
                    shutil.copy2(TEMPLATE_DB_PATH, db_path)
                    shutil.copy2(TEMPLATE_BLOB_PATH, blob_path)

                    # Create Database/BlobStore instances (no migrations needed - schema is in the copy)
                    db = Database(db_path=db_path)
                    blob_store = BlobStore(db_path=blob_path)
                    active_contexts[test_id] = (db, blob_store)

            # Set in g for the proxies to find (outside lock - just dict lookup)
            g.db, g.blob_store = active_contexts[test_id]

            # Initialize mock config for this test context
            with active_contexts_lock:
                if test_id not in _isolated_configs:
                    _isolated_configs[test_id] = DEFAULT_CONFIG.copy()
            set_thread_context(g.db, g.blob_store, _isolated_configs[test_id])

        # Add test-only endpoint to reset database
        from flask import Blueprint

        test_bp = Blueprint("test", __name__)

        @test_bp.route("/test/reset", methods=["POST"])
        def reset_database() -> tuple[dict[str, str], int]:
            """Reset database, blob store, and mock config to clean state for test isolation."""
            from flask import request

            # Reset main database (g.db is already the correct tenant DB)
            with g.db._pool.get_connection() as conn:
                # Delete all data but keep tables
                conn.execute("DELETE FROM message_costs")
                conn.execute("DELETE FROM messages")
                conn.execute("DELETE FROM conversations")
                conn.execute("DELETE FROM user_memories")
                conn.execute("DELETE FROM users")
                conn.commit()

            # Reset blob store
            with g.blob_store._pool.get_connection() as conn:
                conn.execute("DELETE FROM blobs")
                conn.commit()

            # Reset mock config to defaults for this test context
            test_id = request.headers.get("X-Test-Execution-Id", "default-shared-session")
            _isolated_configs[test_id] = DEFAULT_CONFIG.copy()

            return {"status": "reset"}, 200

        @test_bp.route("/test/seed", methods=["POST"])
        def seed_data() -> tuple[dict[str, Any], int]:
            """Seed test data directly into database."""
            from flask import request

            data = request.get_json() or {}
            conversations_data = data.get("conversations", [])
            created_ids = []

            # Get or create the same user that auth bypass uses
            user = g.db.get_or_create_user(
                email="local@localhost",
                name="Local User",
            )

            for conv_data in conversations_data:
                # Create conversation
                title = conv_data.get("title", "Test Conversation")
                conv = g.db.create_conversation(user.id, title=title)
                created_ids.append(conv.id)

                # Add messages
                messages = conv_data.get("messages", [])
                for msg in messages:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    files = msg.get("files")
                    g.db.add_message(conv.id, role, content, files=files)

            return {"status": "seeded", "conversation_ids": created_ids}, 200

        @test_bp.route("/test/simulate-error", methods=["POST"])
        def simulate_error() -> tuple[dict[str, Any], int]:
            """Simulate an error for testing error UI."""
            from src.api.errors import server_error

            return server_error("Simulated server error for testing")

        @test_bp.route("/test/simulate-timeout", methods=["POST"])
        def simulate_timeout() -> tuple[dict[str, Any], int]:
            """Simulate a timeout for testing error UI."""
            time.sleep(10)  # Delay long enough to trigger frontend timeout
            return {"status": "ok"}, 200

        @test_bp.route("/test/set-mock-response", methods=["POST"])
        def set_mock_response() -> tuple[dict[str, str], int]:
            from flask import request

            data = request.get_json() or {}
            response = data.get("response")
            # Uses context-aware MOCK_CONFIG
            MOCK_CONFIG["custom_response"] = response
            return {"status": "set", "response": response or "(default)"}, 200

        @test_bp.route("/test/clear-mock-response", methods=["POST"])
        def clear_mock_response() -> tuple[dict[str, str], int]:
            MOCK_CONFIG["custom_response"] = None
            return {"status": "cleared"}, 200

        @test_bp.route("/test/set-stream-delay", methods=["POST"])
        def set_stream_delay() -> tuple[dict[str, Any], int]:
            from flask import request

            data = request.get_json() or {}
            # Support both delay_ms (int) and delay (float seconds)
            if "delay_ms" in data:
                delay_ms = float(data["delay_ms"])
            else:
                delay_ms = float(data.get("delay", 0.05)) * 1000
            # Uses context-aware MOCK_CONFIG
            MOCK_CONFIG["stream_delay_ms"] = delay_ms
            return {"status": "set", "delay_ms": delay_ms}, 200

        @test_bp.route("/test/set-emit-thinking", methods=["POST"])
        def set_emit_thinking() -> tuple[dict[str, Any], int]:
            from flask import request

            data = request.get_json() or {}
            emit = data.get("emit", True)
            MOCK_CONFIG["emit_thinking"] = emit
            return {"status": "set", "emit_thinking": emit}, 200

        @test_bp.route("/test/set-batch-delay", methods=["POST"])
        def set_batch_delay() -> tuple[dict[str, Any], int]:
            from flask import request

            data = request.get_json() or {}
            # Support both delay_ms (int) and delay (float seconds)
            if "delay_ms" in data:
                delay_ms = float(data["delay_ms"])
            else:
                delay_ms = float(data.get("delay", 0.05)) * 1000
            MOCK_CONFIG["batch_delay_ms"] = delay_ms
            return {"status": "set", "delay_ms": delay_ms}, 200

        @test_bp.route("/test/set-search-results", methods=["POST"])
        def set_search_results() -> tuple[dict[str, Any], int]:
            """Set custom search results for testing search UI."""
            from flask import request

            data = request.get_json() or {}
            MOCK_CONFIG["search_results"] = data.get("results")
            MOCK_CONFIG["search_total"] = data.get("total", 0)
            return {"status": "set"}, 200

        @test_bp.route("/test/clear-search-results", methods=["POST"])
        def clear_search_results() -> tuple[dict[str, str], int]:
            """Clear custom search results to restore default behavior."""
            MOCK_CONFIG["search_results"] = None
            MOCK_CONFIG["search_total"] = 0
            return {"status": "cleared"}, 200

        @test_bp.route("/test/set-planner-integrations", methods=["POST"])
        def set_planner_integrations() -> tuple[dict[str, Any], int]:
            """Set planner integration status for testing."""
            from flask import request

            data = request.get_json() or {}
            MOCK_CONFIG["planner_todoist_connected"] = data.get("todoist", False)
            MOCK_CONFIG["planner_calendar_connected"] = data.get("calendar", False)
            return {
                "status": "set",
                "todoist": MOCK_CONFIG["planner_todoist_connected"],
                "calendar": MOCK_CONFIG["planner_calendar_connected"],
            }, 200

        @test_bp.route("/test/set-planner-dashboard", methods=["POST"])
        def set_planner_dashboard() -> tuple[dict[str, Any], int]:
            """Set custom planner dashboard data for testing."""
            from flask import request

            data = request.get_json() or {}
            MOCK_CONFIG["planner_dashboard"] = data.get("dashboard")
            return {"status": "set"}, 200

        @test_bp.route("/test/add-planner-message", methods=["POST"])
        def add_planner_message() -> tuple[dict[str, Any], int]:
            """Add a dummy message to planner conversation to prevent proactive analysis."""
            user = g.db.get_or_create_user(
                email="local@localhost",
                name="Local User",
            )
            conv = g.db.get_or_create_planner_conversation(user.id)

            # Add a simple assistant message
            g.db.add_message(
                conversation_id=conv.id,
                role="assistant",
                content="Ready to help with your planning!",
                files=None,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
            )
            return {"status": "message_added"}, 200

        @test_bp.route("/test/clear-planner-config", methods=["POST"])
        def clear_planner_config() -> tuple[dict[str, str], int]:
            """Clear planner mock config to restore defaults."""
            MOCK_CONFIG["planner_todoist_connected"] = False
            MOCK_CONFIG["planner_calendar_connected"] = False
            MOCK_CONFIG["planner_dashboard"] = None
            return {"status": "cleared"}, 200

        # =============================================================================
        # Agents test routes
        # =============================================================================

        @test_bp.route("/test/set-agents-command-center", methods=["POST"])
        def set_agents_command_center() -> tuple[dict[str, Any], int]:
            """Set custom agents command center data for testing."""
            from flask import request

            data = request.get_json() or {}
            MOCK_CONFIG["agents_command_center"] = data.get("command_center")
            return {"status": "set"}, 200

        @test_bp.route("/test/clear-agents-config", methods=["POST"])
        def clear_agents_config() -> tuple[dict[str, str], int]:
            """Clear agents mock config to restore defaults."""
            MOCK_CONFIG["agents_command_center"] = None
            MOCK_CONFIG["agents_by_id"] = {}
            return {"status": "cleared"}, 200

        @test_bp.route("/test/set-agent", methods=["POST"])
        def set_agent() -> tuple[dict[str, Any], int]:
            """Set individual agent data for testing GET /api/agents/:id."""
            from flask import request

            data = request.get_json() or {}
            agent_id = data.get("id")
            if not agent_id:
                return {"error": "Agent ID required"}, 400

            if "agents_by_id" not in MOCK_CONFIG:
                MOCK_CONFIG["agents_by_id"] = {}
            MOCK_CONFIG["agents_by_id"][agent_id] = data
            return {"status": "set"}, 200

        @test_bp.route("/test/seed-agent-with-approval", methods=["POST"])
        def seed_agent_with_approval() -> tuple[dict[str, Any], int]:
            """Seed an agent with a conversation containing a pending approval message.

            This is used to test the input blocking when a conversation has a pending approval.
            """
            from flask import request

            data = request.get_json() or {}
            agent_name = data.get("name", "Test Agent")
            approval_description = data.get("description", "Add task: Buy groceries")
            tool_name = data.get("tool_name", "todoist_add_task")

            # Get or create the test user
            user = g.db.get_or_create_user(
                email="local@localhost",
                name="Local User",
            )

            # Create the agent using the proper method
            agent = g.db.create_agent(
                user_id=user.id,
                name=agent_name,
                description="Test agent for E2E",
                system_prompt="You are a test agent.",
                enabled=True,
            )

            # Add trigger message
            from datetime import datetime

            now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
            g.db.add_message(
                conversation_id=agent.conversation_id,
                role="user",
                content=f"[Manual trigger at {now} UTC]",
            )

            # Create the pending approval using the proper method
            approval = g.db.create_approval_request(
                agent_id=agent.id,
                user_id=user.id,
                tool_name=tool_name,
                tool_args="{}",
                description=approval_description,
            )

            # Add approval request message with explicit \n to ensure pattern matching works
            approval_content = (
                f"[approval-request:{approval.id}]\n"
                f"I need your permission to: **{approval_description}**\n\n"
                f"Tool: `{tool_name}`\n\n"
                f"Please approve or reject this action."
            )
            g.db.add_message(
                conversation_id=agent.conversation_id,
                role="assistant",
                content=approval_content,
            )

            return {
                "status": "seeded",
                "agent_id": agent.id,
                "conversation_id": agent.conversation_id,
                "approval_id": approval.id,
            }, 200

        app.register_blueprint(test_bp)

        # Override search endpoint using before_request to intercept /api/search
        @app.before_request
        def intercept_search() -> Any | None:
            from flask import jsonify, request

            if request.path == "/api/search" and request.method == "GET":
                if MOCK_CONFIG.get("search_results") is not None:
                    query = request.args.get("q", "")
                    return jsonify(
                        {
                            "results": MOCK_CONFIG["search_results"],
                            "total": MOCK_CONFIG.get("search_total", 0),
                            "query": query,
                        }
                    )
            return None

        # Override planner endpoints to return mock data
        @app.before_request
        def intercept_planner() -> Any | None:
            from datetime import datetime, timedelta

            from flask import jsonify, request

            # Intercept /api/planner (dashboard)
            if request.path == "/api/planner" and request.method == "GET":
                todoist_connected = MOCK_CONFIG.get("planner_todoist_connected", False)
                calendar_connected = MOCK_CONFIG.get("planner_calendar_connected", False)

                # Return custom dashboard if set
                if MOCK_CONFIG.get("planner_dashboard"):
                    return jsonify(MOCK_CONFIG["planner_dashboard"])

                # Generate default mock dashboard
                today = datetime.now().date()
                days = []
                day_names = ["Today", "Tomorrow"]
                for i in range(7):
                    date = today + timedelta(days=i)
                    day_name = day_names[i] if i < 2 else date.strftime("%A")
                    days.append(
                        {
                            "date": date.isoformat(),
                            "day_name": day_name,
                            "events": [
                                {
                                    "id": f"event-{i}-1",
                                    "summary": f"Meeting {i + 1}",
                                    "start": f"{date.isoformat()}T10:00:00",
                                    "end": f"{date.isoformat()}T11:00:00",
                                    "is_all_day": False,
                                    "location": "Conference Room",
                                    "attendees": [],
                                    "organizer": {
                                        "email": "test@example.com",
                                        "display_name": "Test User",
                                        "self": True,
                                    },
                                    "calendar_id": "primary",
                                    "calendar_summary": "My Calendar",
                                }
                            ]
                            if calendar_connected and i < 3
                            else [],
                            "tasks": [
                                {
                                    "id": f"task-{i}-1",
                                    "content": f"Task {i + 1}",
                                    "priority": 2,
                                    "project_name": "Work",
                                    "due_string": day_name,
                                }
                            ]
                            if todoist_connected and i < 4
                            else [],
                        }
                    )

                return jsonify(
                    {
                        "days": days,
                        "overdue_tasks": [
                            {
                                "id": "task-overdue-1",
                                "content": "Overdue task",
                                "priority": 1,
                                "project_name": "Urgent",
                                "due_string": "Yesterday",
                            }
                        ]
                        if todoist_connected
                        else [],
                        "todoist_connected": todoist_connected,
                        "calendar_connected": calendar_connected,
                        "todoist_error": None,
                        "calendar_error": None,
                        "server_time": datetime.now().isoformat(),
                    }
                )

            # Intercept /api/planner/conversation
            if request.path == "/api/planner/conversation" and request.method == "GET":
                # Get or create a mock planner conversation
                user = g.db.get_or_create_user(
                    email="local@localhost",
                    name="Local User",
                )
                # Get or create planner conversation (single method handles both)
                conv = g.db.get_or_create_planner_conversation(user.id)
                messages = g.db.get_messages(conv.id)

                # For visual tests: always include at least one dummy message to prevent proactive analysis
                if len(messages) == 0:
                    messages = [
                        type(
                            "Message",
                            (),
                            {
                                "id": "dummy-msg-1",
                                "role": "assistant",
                                "content": "Ready to help with your planning!",
                                "created_at": datetime.now(),
                                "files": [],
                            },
                        )()
                    ]

                return jsonify(
                    {
                        "id": conv.id,
                        "title": conv.title,
                        "model": conv.model,
                        "created_at": conv.created_at.isoformat()
                        if hasattr(conv.created_at, "isoformat")
                        else conv.created_at,
                        "updated_at": conv.updated_at.isoformat()
                        if hasattr(conv.updated_at, "isoformat")
                        else conv.updated_at,
                        "messages": [
                            {
                                "id": m.id,
                                "role": m.role,
                                "content": m.content,
                                "created_at": m.created_at.isoformat()
                                if hasattr(m.created_at, "isoformat")
                                else m.created_at,
                                "files": m.files or [],
                            }
                            for m in messages
                        ],
                        "was_reset": False,
                    }
                )

            # Intercept /api/planner/reset
            if request.path == "/api/planner/reset" and request.method == "POST":
                user = g.db.get_or_create_user(
                    email="local@localhost",
                    name="Local User",
                )
                g.db.reset_planner_conversation(user.id)
                return jsonify({"success": True, "message": "Planner conversation reset"})

            # Intercept /auth/todoist/status for planner visibility
            if request.path == "/auth/todoist/status" and request.method == "GET":
                connected = MOCK_CONFIG.get("planner_todoist_connected", False)
                return jsonify(
                    {
                        "connected": connected,
                        "todoist_email": "test@todoist.com" if connected else None,
                        "connected_at": datetime.now().isoformat() if connected else None,
                        "needs_reconnect": False,
                    }
                )

            # Intercept /auth/calendar/status for planner visibility
            if request.path == "/auth/calendar/status" and request.method == "GET":
                connected = MOCK_CONFIG.get("planner_calendar_connected", False)
                return jsonify(
                    {
                        "connected": connected,
                        "calendar_email": "test@gmail.com" if connected else None,
                        "connected_at": datetime.now().isoformat() if connected else None,
                        "needs_reconnect": False,
                    }
                )

            # Intercept /api/agents/command-center for agents testing
            if request.path == "/api/agents/command-center" and request.method == "GET":
                if MOCK_CONFIG.get("agents_command_center"):
                    return jsonify(MOCK_CONFIG["agents_command_center"])
                # Return default empty command center
                return jsonify(
                    {
                        "pending_approvals": [],
                        "agents": [],
                        "recent_executions": [],
                        "total_unread": 0,
                        "agents_waiting": 0,
                    }
                )

            # Intercept /api/agents/:id for individual agent testing
            import re

            agent_match = re.match(r"^/api/agents/([a-zA-Z0-9_-]+)$", request.path)
            if agent_match and request.method == "GET":
                agent_id = agent_match.group(1)
                agents_by_id = MOCK_CONFIG.get("agents_by_id", {})
                if agent_id in agents_by_id:
                    return jsonify(agents_by_id[agent_id])
                # Fall through to real endpoint if no mock data

            return None

        print("Starting E2E test server on http://localhost:8001")
        print("Press Ctrl+C to stop")

        app.run(host="0.0.0.0", port=8001, debug=False, threaded=True)


if __name__ == "__main__":
    main()
