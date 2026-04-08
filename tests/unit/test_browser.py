"""Unit tests for src/agent/tools/browser module."""

import importlib
import json
from unittest.mock import MagicMock, patch

from src.agent.tools.browser import (
    _BLOCKED_NETWORKS,
    _validate_url,
    is_browser_available,
)

# Get the actual module (not the StructuredTool shadowed by __init__.py)
_browser_mod = importlib.import_module("src.agent.tools.browser")


class TestUrlValidation:
    """Tests for URL validation / SSRF protection."""

    def test_allows_https_urls(self) -> None:
        assert _validate_url("https://example.com") is None

    def test_allows_http_urls(self) -> None:
        assert _validate_url("http://example.com") is None

    def test_blocks_file_scheme(self) -> None:
        error = _validate_url("file:///etc/passwd")
        assert error is not None
        assert "Only http://" in error

    def test_blocks_ftp_scheme(self) -> None:
        error = _validate_url("ftp://example.com")
        assert error is not None

    def test_blocks_javascript_scheme(self) -> None:
        error = _validate_url("javascript:alert(1)")
        assert error is not None

    def test_blocks_localhost(self) -> None:
        error = _validate_url("http://localhost:8080")
        assert error is not None
        assert "blocked" in error.lower()

    def test_blocks_127_0_0_1(self) -> None:
        error = _validate_url("http://127.0.0.1")
        assert error is not None
        assert "blocked" in error.lower()

    def test_blocks_private_10_network(self) -> None:
        error = _validate_url("http://10.0.0.1")
        assert error is not None

    def test_blocks_private_172_network(self) -> None:
        error = _validate_url("http://172.16.0.1")
        assert error is not None

    def test_blocks_private_192_168_network(self) -> None:
        error = _validate_url("http://192.168.1.1")
        assert error is not None

    def test_blocks_metadata_ip(self) -> None:
        error = _validate_url("http://169.254.169.254/latest/meta-data")
        assert error is not None

    def test_allows_public_ips(self) -> None:
        assert _validate_url("http://8.8.8.8") is None

    def test_allows_domain_names(self) -> None:
        assert _validate_url("https://www.google.com/search?q=test") is None

    def test_blocks_empty_hostname(self) -> None:
        error = _validate_url("http://")
        assert error is not None

    def test_blocked_networks_list_is_populated(self) -> None:
        """Ensure SSRF blocklist covers essential ranges."""
        assert len(_BLOCKED_NETWORKS) >= 5


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
