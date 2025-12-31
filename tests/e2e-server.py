#!/usr/bin/env python3
"""E2E test server with mocked external services.

This server runs Flask with all external dependencies mocked (LLM, search, etc.).
Playwright auto-starts this server via webServer config.

Usage:
    python tests/e2e-server.py
"""

import base64
import os
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

# Use a unique database file per server run to avoid state pollution between test runs
DB_ID = uuid.uuid4().hex[:8]
E2E_DB_PATH = PROJECT_ROOT / "tests" / f"e2e-test-{DB_ID}.db"
os.environ["DATABASE_PATH"] = str(E2E_DB_PATH)

# Mock configuration (inline - no external files needed)
MOCK_CONFIG: dict[str, Any] = {
    "response_prefix": "This is a mock response to: ",
    "input_tokens": 100,
    "output_tokens": 50,
    "stream_delay_ms": 30,  # Delay between streamed tokens (fast for tests)
    "custom_response": None,  # If set, use this instead of prefix + message
    "emit_thinking": False,  # If True, emit thinking events during streaming
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


def main() -> None:
    """Start the E2E test server with all mocks applied."""
    import contextlib

    from flask import Blueprint

    print("E2E Test Server starting...")
    print(f"Database: {E2E_DB_PATH}")

    # Remove old test database for clean state
    if E2E_DB_PATH.exists():
        E2E_DB_PATH.unlink()

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
        from src.db.models import Database

        # Create test database using E2E_DB_PATH
        test_db = Database(db_path=E2E_DB_PATH)

        # Patch database everywhere
        stack.enter_context(patch("src.db.models.db", test_db))
        stack.enter_context(patch("src.auth.jwt_auth.db", test_db))
        stack.enter_context(patch("src.api.routes.db", test_db))
        stack.enter_context(patch("src.agent.chat_agent.db", test_db))

        app = create_app()
        app.config["TESTING"] = True

        # Add test-only endpoint to reset database
        test_bp = Blueprint("test", __name__)

        @test_bp.route("/test/reset", methods=["POST"])
        def reset_database() -> tuple[dict[str, str], int]:
            """Reset database to clean state for test isolation."""
            with test_db._get_conn() as conn:
                # Delete all data but keep tables
                conn.execute("DELETE FROM message_costs")
                conn.execute("DELETE FROM messages")
                conn.execute("DELETE FROM conversations")
                conn.execute("DELETE FROM user_memories")
                conn.execute("DELETE FROM users")
                conn.commit()
            return {"status": "reset"}, 200

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

        app.register_blueprint(test_bp)

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
            # Clean up database file on shutdown
            if E2E_DB_PATH.exists():
                try:
                    E2E_DB_PATH.unlink()
                    print(f"Cleaned up test database: {E2E_DB_PATH}")
                except Exception as e:
                    print(f"Warning: Could not delete test database: {e}")


if __name__ == "__main__":
    main()
