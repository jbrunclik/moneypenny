"""Shared pytest fixtures for AI Chatbot tests."""

import os
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, User

# Set test environment variables before importing app modules
os.environ["FLASK_ENV"] = "testing"
os.environ["GEMINI_API_KEY"] = "test-api-key"
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["ALLOWED_EMAILS"] = "test@example.com,allowed@example.com"


# -----------------------------------------------------------------------------
# Database fixtures
# -----------------------------------------------------------------------------


@pytest.fixture(scope="session")
def temp_db_dir() -> Generator[Path]:
    """Create a temporary directory for test databases."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_db_path(temp_db_dir: Path, request: pytest.FixtureRequest) -> Path:
    """Create unique database path for each test."""
    # Use test name to create unique DB file
    test_name = request.node.name.replace("[", "_").replace("]", "_").replace("/", "_")
    return temp_db_dir / f"{test_name}.db"


@pytest.fixture
def test_blob_path(temp_db_dir: Path, request: pytest.FixtureRequest) -> Path:
    """Create unique blob store path for each test."""
    test_name = request.node.name.replace("[", "_").replace("]", "_").replace("/", "_")
    return temp_db_dir / f"{test_name}_blobs.db"


@pytest.fixture
def test_database(test_db_path: Path) -> Generator[Database]:
    """Create isolated test database for each test."""
    from src.db.models import Database

    db = Database(db_path=test_db_path)
    yield db
    # Cleanup happens automatically when temp dir is removed


@pytest.fixture
def test_blob_store(test_blob_path: Path):
    """Create isolated blob store for each test.

    This fixture also patches get_blob_store in models.py so that
    database operations use the test blob store instance.
    """
    from src.db.blob_store import BlobStore

    blob_store = BlobStore(db_path=test_blob_path)

    # Patch get_blob_store in models.py so add_message etc. use test blob store
    with patch("src.db.models.get_blob_store", return_value=blob_store):
        yield blob_store


# -----------------------------------------------------------------------------
# Flask app fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def app(test_database: Database, test_blob_store) -> Generator[Flask]:
    """Create Flask test application with isolated database and blob store.

    Uses test_database and test_blob_store fixtures to ensure same instances
    are shared between app routes and test fixtures like test_user.
    """
    with patch("src.db.models.db", test_database):
        with patch("src.auth.jwt_auth.db", test_database):
            with patch("src.api.routes.db", test_database):
                # Patch the global blob store getter to return our test instance
                with patch("src.db.blob_store._blob_store", test_blob_store):
                    with patch("src.db.models.get_blob_store", return_value=test_blob_store):
                        with patch("src.api.routes.get_blob_store", return_value=test_blob_store):
                            from src.app import create_app

                            flask_app = create_app()
                            flask_app.config["TESTING"] = True
                            yield flask_app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Create Flask test client."""
    return app.test_client()


# -----------------------------------------------------------------------------
# User and auth fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def test_user(test_database: Database) -> User:
    """Create test user in database."""
    return test_database.get_or_create_user(
        email="test@example.com",
        name="Test User",
        picture="https://example.com/picture.jpg",
    )


@pytest.fixture
def auth_token(test_user: User) -> str:
    """Generate valid JWT token for test user."""
    from src.auth.jwt_auth import create_token

    return create_token(test_user)


@pytest.fixture
def auth_headers(auth_token: str) -> dict[str, str]:
    """Auth headers for authenticated requests."""
    return {"Authorization": f"Bearer {auth_token}"}


# -----------------------------------------------------------------------------
# Conversation fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def test_conversation(test_database: Database, test_user: User) -> Conversation:
    """Create test conversation."""
    return test_database.create_conversation(
        user_id=test_user.id,
        title="Test Conversation",
        model="gemini-3-flash-preview",
    )


# -----------------------------------------------------------------------------
# Mock fixtures for external services
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_gemini_llm() -> Generator[MagicMock]:
    """Mock ChatGoogleGenerativeAI to avoid real API calls."""
    with patch("src.agent.chat_agent.ChatGoogleGenerativeAI") as mock:
        mock_instance = MagicMock()
        mock_instance.invoke.return_value = MagicMock(
            content="Test response from LLM",
            tool_calls=[],
            usage_metadata={"input_tokens": 100, "output_tokens": 50},
        )
        mock.return_value = mock_instance
        yield mock


@pytest.fixture
def mock_genai_client() -> Generator[MagicMock]:
    """Mock genai.Client for image generation."""
    with patch("src.agent.tools.genai.Client") as mock:
        yield mock


@pytest.fixture
def mock_ddgs() -> Generator[MagicMock]:
    """Mock DuckDuckGo search."""
    with patch("src.agent.tools.DDGS") as mock:
        mock_instance = MagicMock()
        mock_instance.__enter__ = MagicMock(return_value=mock_instance)
        mock_instance.__exit__ = MagicMock(return_value=False)
        mock_instance.text.return_value = [
            {
                "title": "Test Result",
                "href": "https://example.com",
                "body": "Test snippet",
            }
        ]
        mock.return_value = mock_instance
        yield mock


@pytest.fixture
def mock_httpx() -> Generator[MagicMock]:
    """Mock httpx for URL fetching."""
    with patch("src.agent.tools.httpx.Client") as mock:
        mock_instance = MagicMock()
        mock_instance.__enter__ = MagicMock(return_value=mock_instance)
        mock_instance.__exit__ = MagicMock(return_value=False)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body><p>Test content</p></body></html>"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()
        mock_instance.get.return_value = mock_response
        mock.return_value = mock_instance
        yield mock


@pytest.fixture
def mock_google_tokeninfo() -> Generator[MagicMock]:
    """Mock Google tokeninfo endpoint."""
    with patch("src.auth.google_auth.requests.get") as mock:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "aud": "test-client-id",
            "email": "test@example.com",
            "name": "Test User",
            "picture": "https://example.com/pic.jpg",
            "email_verified": "true",
        }
        mock.return_value = mock_response
        yield mock


# -----------------------------------------------------------------------------
# Image fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def sample_png_base64() -> str:
    """Create a simple test PNG image."""
    from tests.fixtures.images import create_test_png

    return create_test_png(100, 100, "red")


@pytest.fixture
def large_png_base64() -> str:
    """Create a large test PNG image (1000x1000)."""
    from tests.fixtures.images import create_test_png

    return create_test_png(1000, 1000, "blue")


@pytest.fixture
def sample_file(sample_png_base64: str) -> dict[str, Any]:
    """Sample file attachment."""
    return {
        "name": "test.png",
        "type": "image/png",
        "data": sample_png_base64,
    }


# -----------------------------------------------------------------------------
# OpenAPI validation fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def openapi_spec(app: Flask) -> dict[str, Any]:
    """Get the OpenAPI spec from the app.

    Uses APIFlask's app.spec property to get the full OpenAPI specification.
    This can be used for response validation in tests.
    """
    return app.spec  # type: ignore[attr-defined]


@pytest.fixture
def openapi_client(client: FlaskClient, app: Flask) -> Generator[FlaskClient]:
    """Create a test client with response validation enabled via APIFlask.

    APIFlask validates responses against OpenAPI schemas when VALIDATION_MODE
    is set to "response". This fixture ensures validation is enabled during tests.

    Note: For tests that need explicit schema validation against the spec,
    use the openapi_spec fixture directly. APIFlask's built-in validation
    handles nested schema references correctly during actual requests.

    Usage:
        def test_endpoint(openapi_client):
            response = openapi_client.get("/api/conversations")
            # Response is automatically validated by APIFlask
            assert response.status_code == 200
    """
    # Ensure response validation is enabled for tests
    original_mode = app.config.get("VALIDATION_MODE")
    app.config["VALIDATION_MODE"] = "response"

    yield client

    # Restore original mode
    app.config["VALIDATION_MODE"] = original_mode
