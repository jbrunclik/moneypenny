"""Unit tests for src/agent/tools/browser module."""

import importlib
import json
import socket
from unittest.mock import MagicMock, patch

import pytest

from src.agent.tools.browser import (
    is_browser_available,
)

# Get the actual module (not the StructuredTool shadowed by __init__.py)
_browser_mod = importlib.import_module("src.agent.tools.browser")

# URL/SSRF validation now lives in src/agent/tools/url_safety.py;
# see tests/unit/test_url_safety.py for its coverage.


class TestBrowserLaunchArgs:
    """Chromium OS sandbox stays on unless explicitly opted out (S8)."""

    def test_sandbox_on_by_default(self) -> None:
        with patch.object(_browser_mod.Config, "BROWSER_NO_SANDBOX", False):
            assert "--no-sandbox" not in _browser_mod._browser_launch_args()

    def test_no_sandbox_opt_out(self) -> None:
        with patch.object(_browser_mod.Config, "BROWSER_NO_SANDBOX", True):
            assert "--no-sandbox" in _browser_mod._browser_launch_args()


class TestBrowserAvailability:
    """Tests for is_browser_available check."""

    def test_returns_bool(self) -> None:
        """is_browser_available should return a bool without crashing."""
        _browser_mod._browser_available = None
        result = is_browser_available()
        assert isinstance(result, bool)

    def test_caches_result(self) -> None:
        """Subsequent calls should return the cached value."""
        _browser_mod._browser_available = True
        assert is_browser_available() is True
        _browser_mod._browser_available = False
        assert is_browser_available() is False
        # Reset for other tests
        _browser_mod._browser_available = None


class TestBrowserTool:
    """Tests for the browser tool function."""

    @pytest.fixture(autouse=True)
    def _public_dns(self):
        """Resolve hostnames to a public IP so SSRF validation passes offline."""
        addrinfo = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0))
        ]
        with patch("src.agent.tools.url_safety.socket.getaddrinfo", return_value=addrinfo):
            yield

    @patch("src.agent.tools.browser.Config")
    def test_disabled_returns_error(self, mock_config: MagicMock) -> None:
        """Should return error when BROWSER_ENABLED is False."""
        mock_config.BROWSER_ENABLED = False
        from src.agent.tools.browser import browser

        result = browser.invoke({"action": "navigate", "url": "https://example.com"})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "disabled" in parsed["error"].lower()

    @patch("src.agent.tools.browser.is_browser_available", return_value=False)
    @patch("src.agent.tools.browser.Config")
    def test_unavailable_returns_error(
        self, mock_config: MagicMock, _mock_avail: MagicMock
    ) -> None:
        """Should return error when Playwright is not installed."""
        mock_config.BROWSER_ENABLED = True
        from src.agent.tools.browser import browser

        result = browser.invoke({"action": "navigate", "url": "https://example.com"})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "playwright" in parsed["error"].lower()

    @patch("src.agent.tools.browser.is_browser_available", return_value=True)
    @patch("src.agent.tools.browser.Config")
    def test_invalid_action_returns_error(
        self, mock_config: MagicMock, _mock_avail: MagicMock
    ) -> None:
        """Should return error for unknown actions."""
        mock_config.BROWSER_ENABLED = True
        from src.agent.tools.browser import browser

        result = browser.invoke({"action": "invalid_action"})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "Unknown action" in parsed["error"]

    @patch("src.agent.tools.browser.is_browser_available", return_value=True)
    @patch("src.agent.tools.browser.Config")
    def test_navigate_validates_url_localhost(
        self, mock_config: MagicMock, _mock_avail: MagicMock
    ) -> None:
        """Navigate to localhost should be blocked before reaching worker."""
        mock_config.BROWSER_ENABLED = True
        from src.agent.tools.browser import browser

        result = browser.invoke({"action": "navigate", "url": "http://127.0.0.1"})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "blocked" in parsed["error"].lower()

    @patch("src.agent.tools.browser.is_browser_available", return_value=True)
    @patch("src.agent.tools.browser.Config")
    def test_navigate_requires_url(self, mock_config: MagicMock, _mock_avail: MagicMock) -> None:
        """Navigate without url should return error."""
        mock_config.BROWSER_ENABLED = True
        from src.agent.tools.browser import browser

        result = browser.invoke({"action": "navigate"})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "url" in parsed["error"].lower()

    @patch("src.agent.tools.browser.is_browser_available", return_value=True)
    @patch("src.agent.tools.browser.Config")
    def test_click_requires_selector(self, mock_config: MagicMock, _mock_avail: MagicMock) -> None:
        """Click without selector should return error."""
        mock_config.BROWSER_ENABLED = True
        from src.agent.tools.browser import browser

        result = browser.invoke({"action": "click"})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "selector" in parsed["error"].lower()

    @patch("src.agent.tools.browser.is_browser_available", return_value=True)
    @patch("src.agent.tools.browser.Config")
    def test_type_requires_selector_and_text(
        self, mock_config: MagicMock, _mock_avail: MagicMock
    ) -> None:
        """Type without selector or text should return error."""
        mock_config.BROWSER_ENABLED = True
        from src.agent.tools.browser import browser

        # Missing selector
        result = browser.invoke({"action": "type", "text": "hello"})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "selector" in parsed["error"].lower()

        # Missing text
        result = browser.invoke({"action": "type", "selector": "#input"})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "text" in parsed["error"].lower()

    @patch("src.agent.tools.browser._start_cleanup_thread")
    @patch("src.agent.tools.browser._get_worker")
    @patch("src.agent.tools.browser.is_browser_available", return_value=True)
    @patch("src.agent.tools.browser.Config")
    def test_navigate_success(
        self,
        mock_config: MagicMock,
        _mock_avail: MagicMock,
        mock_get_worker: MagicMock,
        _mock_cleanup: MagicMock,
    ) -> None:
        """Successful navigation returns page info."""
        mock_config.BROWSER_ENABLED = True
        mock_config.BROWSER_PAGE_TIMEOUT_MS = 30000

        mock_worker = MagicMock()
        mock_worker.execute.return_value = {
            "success": True,
            "title": "Example Domain",
            "url": "https://example.com",
        }
        mock_get_worker.return_value = mock_worker

        from src.agent.tools.browser import browser

        result = browser.invoke({"action": "navigate", "url": "https://example.com"})
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["title"] == "Example Domain"
        mock_worker.execute.assert_called_once()

    @patch("src.agent.tools.browser._start_cleanup_thread")
    @patch("src.agent.tools.browser._get_worker")
    @patch("src.agent.tools.browser.is_browser_available", return_value=True)
    @patch("src.agent.tools.browser.Config")
    def test_screenshot_returns_multimodal_for_llm(
        self,
        mock_config: MagicMock,
        _mock_avail: MagicMock,
        mock_get_worker: MagicMock,
        _mock_cleanup: MagicMock,
    ) -> None:
        """Screenshot should return multimodal content so the LLM can see the image."""
        mock_config.BROWSER_ENABLED = True

        mock_worker = MagicMock()
        mock_worker.execute.return_value = {
            "url": "https://example.com",
            "size": 1234,
            "mime_type": "image/jpeg",
            "data": "base64data",
        }
        mock_get_worker.return_value = mock_worker

        from src.agent.tools.browser import browser

        result = browser.invoke({"action": "screenshot"})
        # Should be multimodal content (list), not JSON string
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "image"
        assert result[1]["mime_type"] == "image/jpeg"

    @patch("src.agent.tools.browser._save_screenshot_attachment")
    @patch("src.agent.tools.browser._start_cleanup_thread")
    @patch("src.agent.tools.browser._get_worker")
    @patch("src.agent.tools.browser.is_browser_available", return_value=True)
    @patch("src.agent.tools.browser.Config")
    def test_shared_screenshot_saves_attachment(
        self,
        mock_config: MagicMock,
        _mock_avail: MagicMock,
        mock_get_worker: MagicMock,
        _mock_cleanup: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        """share_screenshot=True should save an attachment for the user."""
        mock_config.BROWSER_ENABLED = True

        mock_worker = MagicMock()
        mock_worker.execute.return_value = {
            "url": "https://example.com",
            "size": 1234,
            "mime_type": "image/jpeg",
            "data": "base64data",
        }
        mock_get_worker.return_value = mock_worker

        from src.agent.tools.browser import browser

        result = browser.invoke({"action": "screenshot", "share_screenshot": True})
        # Still returns multimodal for the LLM
        assert isinstance(result, list)
        # Also saved attachment for the user
        mock_save.assert_called_once()

    @patch("src.agent.tools.browser._start_cleanup_thread")
    @patch("src.agent.tools.browser._get_worker")
    @patch("src.agent.tools.browser.is_browser_available", return_value=True)
    @patch("src.agent.tools.browser.Config")
    def test_extract_returns_page_content(
        self,
        mock_config: MagicMock,
        _mock_avail: MagicMock,
        mock_get_worker: MagicMock,
        _mock_cleanup: MagicMock,
    ) -> None:
        """Extract should return page text content."""
        mock_config.BROWSER_ENABLED = True

        mock_worker = MagicMock()
        mock_worker.execute.return_value = {
            "success": True,
            "title": "Test Page",
            "url": "https://example.com",
            "content": "Hello Browser",
        }
        mock_get_worker.return_value = mock_worker

        from src.agent.tools.browser import browser

        result = browser.invoke({"action": "extract"})
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert "Hello Browser" in parsed["content"]

    @patch("src.agent.tools.browser._start_cleanup_thread")
    @patch("src.agent.tools.browser._get_worker")
    @patch("src.agent.tools.browser.is_browser_available", return_value=True)
    @patch("src.agent.tools.browser.Config")
    def test_close_delegates_to_worker(
        self,
        mock_config: MagicMock,
        _mock_avail: MagicMock,
        mock_get_worker: MagicMock,
        _mock_cleanup: MagicMock,
    ) -> None:
        """Close action should delegate to the worker."""
        mock_config.BROWSER_ENABLED = True

        mock_worker = MagicMock()
        mock_worker.execute.return_value = {
            "success": True,
            "message": "Browser session closed.",
        }
        mock_get_worker.return_value = mock_worker

        from src.agent.tools.browser import browser

        result = browser.invoke({"action": "close"})
        parsed = json.loads(result)
        assert parsed["success"] is True
        mock_worker.execute.assert_called_once()

    @patch("src.agent.tools.browser._start_cleanup_thread")
    @patch("src.agent.tools.browser._get_worker")
    @patch("src.agent.tools.browser.is_browser_available", return_value=True)
    @patch("src.agent.tools.browser.Config")
    def test_timeout_error_gives_hint(
        self,
        mock_config: MagicMock,
        _mock_avail: MagicMock,
        mock_get_worker: MagicMock,
        _mock_cleanup: MagicMock,
    ) -> None:
        """Timeout errors should include helpful hints."""
        mock_config.BROWSER_ENABLED = True
        mock_config.TOOL_TIMEOUT = 90

        mock_worker = MagicMock()
        mock_worker.execute.side_effect = TimeoutError("timed out")
        mock_get_worker.return_value = mock_worker

        from src.agent.tools.browser import browser

        result = browser.invoke({"action": "navigate", "url": "https://slow-site.com"})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "timed out" in parsed["error"].lower()
        assert "hint" in parsed
