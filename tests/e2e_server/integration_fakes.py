"""Fakes for external services: web search and fetch, Gemini files and
images, Google token validation."""

import base64
from typing import Any
from unittest.mock import MagicMock


def mock_search_web(query: str, num_results: int) -> list[dict[str, str]]:
    """Mock the search-provider seam (research uses it directly)."""
    return [
        {
            "title": "Example Search Result",
            "url": "https://example.com/result",
            "snippet": "This is a mock search result snippet.",
        }
    ]


def mock_search_web_detailed(query: str, num_results: int) -> tuple[list[dict[str, str]], str]:
    """web_search's seam: results plus the provider that actually served."""
    return mock_search_web(query, num_results), "brave"


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


def create_mock_gemini_files_client() -> MagicMock:
    """Mock the Gemini Files API client used for video uploads."""
    from types import SimpleNamespace

    client = MagicMock()
    uploaded = SimpleNamespace(
        name="files/e2e-mock",
        uri="https://files.example/e2e-mock",
        state=SimpleNamespace(name="ACTIVE"),
    )
    client.files.upload.return_value = uploaded
    client.files.get.return_value = uploaded
    return MagicMock(return_value=client)


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
