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
import time
import uuid
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

# Use unique database files per server run to avoid state pollution between test runs
DB_ID = uuid.uuid4().hex[:8]
E2E_DB_PATH = PROJECT_ROOT / "tests" / f"e2e-test-{DB_ID}.db"
E2E_BLOB_PATH = PROJECT_ROOT / "tests" / f"e2e-test-{DB_ID}-blobs.db"
os.environ["DATABASE_PATH"] = str(E2E_DB_PATH)
os.environ["BLOB_STORAGE_PATH"] = str(E2E_BLOB_PATH)

# PID file for cleanup
E2E_PID_FILE = PROJECT_ROOT / ".e2e-server.pid"

# Mock configuration (inline - no external files needed)
MOCK_CONFIG: dict[str, Any] = {
    "response_prefix": "This is a mock response to: ",
    "input_tokens": 100,
    "output_tokens": 50,
    "stream_delay_ms": 10,  # Delay between streamed tokens (very fast for tests)
    "batch_delay_ms": 0,  # Delay before batch response (for testing conversation switching)
    "custom_response": None,  # If set, use this instead of prefix + message
    "emit_thinking": False,  # If True, emit thinking events during streaming
    "search_results": None,  # If set, return these instead of real search results
    "search_total": 0,  # Total count for mocked search results
}


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


def signal_handler(signum: int, frame: Any) -> None:
    """Handle signals and cleanup PID file."""
    cleanup_pid_file()
    sys.exit(0)


def main() -> None:
    """Start the E2E test server with all mocks applied."""
    import contextlib

    from flask import Blueprint

    # Write PID file
    try:
        E2E_PID_FILE.write_text(str(os.getpid()))
        atexit.register(cleanup_pid_file)
        # Also register signal handlers for cleanup
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
    except Exception as e:
        print(f"Warning: Could not write PID file: {e}")

    print("E2E Test Server starting...")
    print(f"Database: {E2E_DB_PATH}")
    print(f"Blob store: {E2E_BLOB_PATH}")

    # Remove old test database files for clean state
    if E2E_DB_PATH.exists():
        E2E_DB_PATH.unlink()
    if E2E_BLOB_PATH.exists():
        E2E_BLOB_PATH.unlink()

    # Use ExitStack to avoid deep nesting of context managers
    with contextlib.ExitStack() as stack:
        # Apply external service mocks
        stack.enter_context(patch("src.agent.chat_agent.ChatGoogleGenerativeAI", create_mock_llm()))
        stack.enter_context(patch("src.agent.tools.DDGS", create_mock_ddgs()))
        stack.enter_context(patch("src.agent.tools.httpx.Client", create_mock_httpx()))
        stack.enter_context(patch("src.agent.tools.genai.Client", create_mock_genai()))
        stack.enter_context(
            patch("src.auth.google_auth.requests.get", create_mock_google_tokeninfo())
        )
        stack.enter_context(
            patch("src.agent.chat_agent.ChatAgent.stream_chat", create_mock_stream_chat())
        )
        stack.enter_context(
            patch(
                "src.agent.chat_agent.ChatAgent.stream_chat_events",
                create_mock_stream_chat_events(),
            )
        )

        # Import app after mocks are in place
        from src.app import create_app
        from src.db.blob_store import BlobStore
        from src.db.models import Database

        # Create test database using E2E_DB_PATH
        test_db = Database(db_path=E2E_DB_PATH)

        # Create test blob store using E2E_BLOB_PATH
        test_blob_store = BlobStore(db_path=E2E_BLOB_PATH)

        # Patch database everywhere
        stack.enter_context(patch("src.db.models.db", test_db))
        stack.enter_context(patch("src.auth.jwt_auth.db", test_db))
        stack.enter_context(patch("src.api.routes.db", test_db))
        stack.enter_context(patch("src.agent.chat_agent.db", test_db))

        # Patch blob store everywhere it's used
        stack.enter_context(patch("src.db.blob_store._blob_store", test_blob_store))
        stack.enter_context(patch("src.db.models.get_blob_store", return_value=test_blob_store))
        stack.enter_context(patch("src.api.routes.get_blob_store", return_value=test_blob_store))

        app = create_app()
        app.config["TESTING"] = True

        # Add test-only endpoint to reset database
        test_bp = Blueprint("test", __name__)

        @test_bp.route("/test/reset", methods=["POST"])
        def reset_database() -> tuple[dict[str, str], int]:
            """Reset database and blob store to clean state for test isolation."""
            # Reset main database
            with test_db._pool.get_connection() as conn:
                # Delete all data but keep tables
                conn.execute("DELETE FROM message_costs")
                conn.execute("DELETE FROM messages")
                conn.execute("DELETE FROM conversations")
                conn.execute("DELETE FROM user_memories")
                conn.execute("DELETE FROM users")
                conn.commit()

            # Reset blob store
            with test_blob_store._pool.get_connection() as conn:
                conn.execute("DELETE FROM blobs")
                conn.commit()

            return {"status": "reset"}, 200

        @test_bp.route("/test/seed", methods=["POST"])
        def seed_data() -> tuple[dict[str, Any], int]:
            """Seed test data directly into database for faster test setup.

            Request body:
            {
                "conversations": [
                    {
                        "title": "Optional title",
                        "messages": [
                            {"role": "user", "content": "Hello"},
                            {"role": "assistant", "content": "Hi there!"}
                        ]
                    }
                ]
            }

            Returns created conversation IDs.
            """
            from flask import request

            data = request.get_json() or {}
            conversations_data = data.get("conversations", [])
            created_ids = []

            # Get or create the same user that auth bypass uses
            # This must match the user in jwt_auth.py's bypass_auth logic
            user = test_db.get_or_create_user(
                email="local@localhost",
                name="Local User",
            )

            for conv_data in conversations_data:
                # Create conversation
                title = conv_data.get("title", "Test Conversation")
                conv = test_db.create_conversation(user.id, title=title)
                created_ids.append(conv.id)

                # Add messages
                messages = conv_data.get("messages", [])
                for msg in messages:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    files = msg.get("files")
                    test_db.add_message(conv.id, role, content, files=files)

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
            """Set a custom mock response for testing specific content."""
            from flask import request

            data = request.get_json() or {}
            response = data.get("response")
            MOCK_CONFIG["custom_response"] = response
            return {"status": "set", "response": response or "(default)"}, 200

        @test_bp.route("/test/clear-mock-response", methods=["POST"])
        def clear_mock_response() -> tuple[dict[str, str], int]:
            """Clear custom mock response to restore default behavior."""
            MOCK_CONFIG["custom_response"] = None
            return {"status": "cleared"}, 200

        @test_bp.route("/test/set-emit-thinking", methods=["POST"])
        def set_emit_thinking() -> tuple[dict[str, Any], int]:
            """Enable/disable thinking events for testing thinking indicator UI."""
            from flask import request

            data = request.get_json() or {}
            emit = data.get("emit", True)
            MOCK_CONFIG["emit_thinking"] = emit
            return {"status": "set", "emit_thinking": emit}, 200

        @test_bp.route("/test/set-stream-delay", methods=["POST"])
        def set_stream_delay() -> tuple[dict[str, Any], int]:
            """Set the delay between streamed tokens for testing conversation switching."""
            from flask import request

            data = request.get_json() or {}
            delay_ms = data.get("delay_ms", 30)
            MOCK_CONFIG["stream_delay_ms"] = delay_ms
            return {"status": "set", "stream_delay_ms": delay_ms}, 200

        @test_bp.route("/test/set-batch-delay", methods=["POST"])
        def set_batch_delay() -> tuple[dict[str, Any], int]:
            """Set the delay for batch responses for testing conversation switching."""
            from flask import request

            data = request.get_json() or {}
            delay_ms = data.get("delay_ms", 0)
            MOCK_CONFIG["batch_delay_ms"] = delay_ms
            return {"status": "set", "batch_delay_ms": delay_ms}, 200

        @test_bp.route("/test/set-search-results", methods=["POST"])
        def set_search_results() -> tuple[dict[str, Any], int]:
            """Set custom search results for testing search UI.

            Request body:
            {
                "results": [
                    {
                        "conversation_id": "conv-123",
                        "conversation_title": "Test Conversation",
                        "message_id": "msg-456",  // optional
                        "message_snippet": "...matching text...",  // optional
                        "match_type": "message",  // or "conversation"
                        "created_at": "2024-01-01T12:00:00"  // optional
                    }
                ],
                "total": 1
            }

            If not set, the real search endpoint is used.
            """
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

        app.register_blueprint(test_bp)

        # Override search endpoint using before_request to intercept /api/search
        # This must be done AFTER blueprint registration so it takes priority
        @app.before_request
        def intercept_search() -> Any | None:
            """Intercept /api/search requests to return mock results if configured.

            If MOCK_CONFIG["search_results"] is set, returns those results.
            Otherwise, lets the request continue to the real search endpoint.
            """
            from flask import jsonify, request

            if request.path == "/api/search" and request.method == "GET":
                if MOCK_CONFIG["search_results"] is not None:
                    query = request.args.get("q", "")
                    return jsonify(
                        {
                            "results": MOCK_CONFIG["search_results"],
                            "total": MOCK_CONFIG["search_total"],
                            "query": query,
                        }
                    )
            return None  # Continue to normal handling

        print("Starting E2E test server on http://localhost:8001")
        print("Press Ctrl+C to stop")

        # Run with threading for better performance
        try:
            app.run(
                host="0.0.0.0",
                port=8001,
                debug=False,
                threaded=True,
            )
        finally:
            # Clean up PID file
            cleanup_pid_file()
            # Clean up database files on shutdown
            for path, name in [(E2E_DB_PATH, "database"), (E2E_BLOB_PATH, "blob store")]:
                if path.exists():
                    try:
                        path.unlink()
                        print(f"Cleaned up test {name}: {path}")
                    except Exception as e:
                        print(f"Warning: Could not delete test {name}: {e}")


if __name__ == "__main__":
    main()
