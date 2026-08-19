"""Tests for the pluggable search provider (Brave with DDGS fallback)."""

from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.utils.search_provider import (
    SearchProviderError,
    active_provider,
    search_web,
)


class TestActiveProvider:
    def test_ddgs_when_no_brave_key(self) -> None:
        with patch.object(Config, "BRAVE_SEARCH_API_KEY", ""):
            assert active_provider() == "ddgs"

    def test_brave_when_key_set(self) -> None:
        with patch.object(Config, "BRAVE_SEARCH_API_KEY", "test-key"):
            assert active_provider() == "brave"


class TestBraveSearch:
    @patch.object(Config, "BRAVE_SEARCH_API_KEY", "test-key")
    @patch("src.utils.search_provider.httpx.get")
    def test_maps_brave_results_to_contract(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "web": {
                "results": [
                    {"title": "T1", "url": "https://a.example", "description": "D1"},
                    {"title": "T2", "url": "https://b.example", "description": "D2"},
                ]
            }
        }
        mock_get.return_value = mock_response

        results = search_web("test query", 2)

        assert results == [
            {"title": "T1", "url": "https://a.example", "snippet": "D1"},
            {"title": "T2", "url": "https://b.example", "snippet": "D2"},
        ]
        # The API key must ride in the subscription header
        assert mock_get.call_args.kwargs["headers"]["X-Subscription-Token"] == "test-key"

    @patch.object(Config, "BRAVE_SEARCH_API_KEY", "test-key")
    @patch("src.utils.search_provider.httpx.get")
    def test_brave_rate_limit_raises_retriable(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_get.return_value = mock_response

        with pytest.raises(SearchProviderError) as exc_info:
            search_web("test query", 2)
        assert exc_info.value.retriable is True

    @patch.object(Config, "BRAVE_SEARCH_API_KEY", "test-key")
    @patch("src.utils.search_provider.httpx.get")
    def test_brave_caps_results(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "web": {
                "results": [{"title": f"T{i}", "url": f"https://{i}.example"} for i in range(10)]
            }
        }
        mock_get.return_value = mock_response

        assert len(search_web("q", 3)) == 3


class TestDdgsSearch:
    @patch.object(Config, "BRAVE_SEARCH_API_KEY", "")
    @patch("src.utils.search_provider.DDGS")
    def test_maps_ddgs_results_to_contract(self, mock_ddgs_class: MagicMock) -> None:
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = [
            {"title": "T1", "href": "https://a.example", "body": "B1"},
        ]
        mock_ddgs_class.return_value = mock_ddgs

        results = search_web("test query", 5)

        assert results == [{"title": "T1", "url": "https://a.example", "snippet": "B1"}]

    @patch.object(Config, "BRAVE_SEARCH_API_KEY", "")
    @patch("src.utils.search_provider.DDGS")
    def test_ddgs_rate_limit_raises_retriable(self, mock_ddgs_class: MagicMock) -> None:
        from ddgs.exceptions import RatelimitException

        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.side_effect = RatelimitException("rate limited")
        mock_ddgs_class.return_value = mock_ddgs

        with pytest.raises(SearchProviderError) as exc_info:
            search_web("q", 5)
        assert exc_info.value.retriable is True
