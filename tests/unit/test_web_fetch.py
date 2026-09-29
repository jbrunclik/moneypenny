"""Unit tests for fetch_url and content-type handling in src/agent/tools/web.py."""

import json
import socket
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.agent.tools import (
    FETCHABLE_BINARY_TYPES,
    fetch_url,
)
from src.agent.tools.web import _get_content_type_category


class TestFetchUrl:
    """Tests for fetch_url tool."""

    @pytest.fixture(autouse=True)
    def _public_dns(self):
        """Resolve any hostname to a public IP so SSRF validation passes in tests."""
        addrinfo = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0))
        ]
        with patch("src.agent.tools.url_safety.socket.getaddrinfo", return_value=addrinfo):
            yield

    @patch("src.agent.tools.web.httpx.Client")
    def test_fetches_html_content(self, mock_client_class: MagicMock) -> None:
        """Should fetch and extract text from HTML pages."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.text = "<html><body><p>Hello World</p></body></html>"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = fetch_url.invoke({"url": "https://example.com"})

        assert "Hello World" in result
        # Fetched content is framed as untrusted (prompt-injection mitigation)
        assert "UNTRUSTED WEB CONTENT" in result
        mock_client.get.assert_called_once_with("https://example.com")

    def test_rejects_invalid_url_scheme(self) -> None:
        """Should reject URLs without http/https scheme."""
        result = fetch_url.invoke({"url": "not-a-url"})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "http" in parsed["error"].lower()

    def test_rejects_ftp_url(self) -> None:
        """Should reject non-HTTP URLs."""
        result = fetch_url.invoke({"url": "ftp://example.com/file.txt"})
        parsed = json.loads(result)
        assert "error" in parsed

    @patch("src.agent.tools.web.httpx.Client")
    def test_handles_timeout(self, mock_client_class: MagicMock) -> None:
        """Should return error on timeout."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("Timeout")
        mock_client_class.return_value = mock_client

        result = fetch_url.invoke({"url": "https://slow.example.com"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "timed out" in parsed["error"]

    @patch("src.agent.tools.web.httpx.Client")
    def test_handles_http_error(self, mock_client_class: MagicMock) -> None:
        """Should return error for HTTP errors."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "Not found", request=MagicMock(), response=mock_response
        )
        mock_client_class.return_value = mock_client

        result = fetch_url.invoke({"url": "https://example.com/404"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "404" in parsed["error"]

    @patch("src.agent.tools.web.httpx.Client")
    def test_rejects_unsupported_content_type(self, mock_client_class: MagicMock) -> None:
        """Should return error for unsupported content types."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.headers = {"content-type": "application/octet-stream"}
        mock_response.content = b"binary data"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = fetch_url.invoke({"url": "https://example.com/file.bin"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "Unsupported content type" in parsed["error"]

    @patch("src.agent.tools.web.httpx.Client")
    def test_fetches_pdf_content(self, mock_client_class: MagicMock) -> None:
        """Should fetch PDF and return multimodal content for LLM analysis."""
        pdf_content = b"%PDF-1.4 fake pdf content"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.content = pdf_content
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = fetch_url.invoke({"url": "https://example.com/document.pdf"})

        # Result should be a list (multimodal content), not a string
        assert isinstance(result, list)
        assert len(result) == 2

        # First block should be text description
        assert result[0]["type"] == "text"
        assert "document.pdf" in result[0]["text"]
        assert "application/pdf" in result[0]["text"]

        # Second block should be the PDF data for LLM analysis
        assert result[1]["type"] == "image"  # LangChain uses "image" for PDFs
        assert result[1]["mime_type"] == "application/pdf"
        import base64

        assert result[1]["base64"] == base64.b64encode(pdf_content).decode("utf-8")

    @patch("src.agent.tools.web.httpx.Client")
    def test_fetches_image_content(self, mock_client_class: MagicMock) -> None:
        """Should fetch images and return multimodal content for LLM analysis."""
        # Minimal valid PNG header
        png_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.headers = {"content-type": "image/png"}
        mock_response.content = png_content
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = fetch_url.invoke({"url": "https://example.com/image.png"})

        assert isinstance(result, list)
        assert len(result) == 2

        # Text description
        assert result[0]["type"] == "text"
        assert "image.png" in result[0]["text"]

        # Image data for LLM analysis
        assert result[1]["type"] == "image"
        assert result[1]["mime_type"] == "image/png"

    @patch("src.agent.tools.web.httpx.Client")
    def test_normalizes_jpg_to_jpeg(self, mock_client_class: MagicMock) -> None:
        """Should normalize image/jpg to image/jpeg."""
        jpg_content = b"\xff\xd8\xff" + b"\x00" * 100
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.headers = {"content-type": "image/jpg"}
        mock_response.content = jpg_content
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = fetch_url.invoke({"url": "https://example.com/photo.jpg"})

        assert isinstance(result, list)
        assert result[1]["mime_type"] == "image/jpeg"  # Normalized

    @patch("src.agent.tools.web.Config.FETCH_URL_MAX_FILE_SIZE", 1000)
    @patch("src.agent.tools.web.httpx.Client")
    def test_rejects_oversized_files(self, mock_client_class: MagicMock) -> None:
        """Should reject files larger than the configured limit."""
        large_content = b"\x00" * 2000  # 2KB, over the 1KB limit
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.content = large_content
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = fetch_url.invoke({"url": "https://example.com/large.pdf"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "too large" in parsed["error"]

    @patch("src.agent.tools.web.httpx.Client")
    def test_handles_plain_text_content(self, mock_client_class: MagicMock) -> None:
        """Should handle plain text content type."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.text = "This is plain text content"
        mock_response.content = b"This is plain text content"
        mock_response.headers = {"content-type": "text/plain; charset=utf-8"}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = fetch_url.invoke({"url": "https://example.com/file.txt"})

        assert isinstance(result, str)
        assert "This is plain text content" in result

    @patch("src.agent.tools.web.httpx.Client")
    def test_blocks_redirect_to_private_address(self, mock_client_class: MagicMock) -> None:
        """A redirect into a blocked IP range must be rejected, not followed."""
        redirect = MagicMock()
        redirect.is_redirect = True
        redirect.headers = {"location": "http://169.254.169.254/latest/meta-data"}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = redirect
        mock_client_class.return_value = mock_client

        result = fetch_url.invoke({"url": "https://example.com/redirect"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "redirect" in parsed["error"].lower()


class TestGetContentTypeCategory:
    """Tests for _get_content_type_category helper function."""

    def test_categorizes_html(self) -> None:
        """Should categorize HTML content types as 'html'."""
        assert _get_content_type_category("text/html") == "html"
        assert _get_content_type_category("text/html; charset=utf-8") == "html"

    def test_categorizes_text(self) -> None:
        """Should categorize plain text types as 'text'."""
        assert _get_content_type_category("text/plain") == "text"
        assert _get_content_type_category("text/markdown") == "text"
        assert _get_content_type_category("text/csv") == "text"
        assert _get_content_type_category("text/plain; charset=utf-8") == "text"

    def test_categorizes_pdf_as_binary(self) -> None:
        """Should categorize PDF as 'binary'."""
        assert _get_content_type_category("application/pdf") == "binary"

    def test_categorizes_images_as_binary(self) -> None:
        """Should categorize image types as 'binary'."""
        assert _get_content_type_category("image/png") == "binary"
        assert _get_content_type_category("image/jpeg") == "binary"
        assert _get_content_type_category("image/jpg") == "binary"
        assert _get_content_type_category("image/gif") == "binary"
        assert _get_content_type_category("image/webp") == "binary"

    def test_categorizes_unsupported_types(self) -> None:
        """Should categorize unknown types as 'unsupported'."""
        assert _get_content_type_category("application/octet-stream") == "unsupported"
        assert _get_content_type_category("application/zip") == "unsupported"
        assert _get_content_type_category("video/mp4") == "unsupported"
        assert _get_content_type_category("audio/mpeg") == "unsupported"

    def test_handles_case_insensitivity(self) -> None:
        """Should handle uppercase content types."""
        assert _get_content_type_category("TEXT/HTML") == "html"
        assert _get_content_type_category("Application/PDF") == "binary"
        assert _get_content_type_category("IMAGE/PNG") == "binary"


class TestFetchableBinaryTypes:
    """Tests for FETCHABLE_BINARY_TYPES constant."""

    def test_includes_pdf(self) -> None:
        """Should include PDF in fetchable types."""
        assert "application/pdf" in FETCHABLE_BINARY_TYPES

    def test_includes_common_image_formats(self) -> None:
        """Should include common image formats."""
        assert "image/png" in FETCHABLE_BINARY_TYPES
        assert "image/jpeg" in FETCHABLE_BINARY_TYPES
        assert "image/gif" in FETCHABLE_BINARY_TYPES
        assert "image/webp" in FETCHABLE_BINARY_TYPES


class TestFetchPageText:
    """Tests for the reusable fetch_page_text helper (used by research)."""

    @pytest.fixture(autouse=True)
    def _public_dns(self):
        """Resolve any hostname to a public IP so SSRF validation passes in tests."""
        addrinfo = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0))
        ]
        with patch("src.agent.tools.url_safety.socket.getaddrinfo", return_value=addrinfo):
            yield

    def _client_returning(self, mock_client_class: MagicMock, mock_response: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

    @patch("src.agent.tools.web.httpx.Client")
    def test_returns_text_for_html(self, mock_client_class: MagicMock) -> None:
        from src.agent.tools.web import fetch_page_text

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.text = "<html><body><p>Hello Research</p></body></html>"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()
        self._client_returning(mock_client_class, mock_response)

        text, error = fetch_page_text("https://example.com")

        assert error is None
        assert text is not None
        assert "Hello Research" in text

    @patch("src.agent.tools.web.httpx.Client")
    def test_respects_max_chars(self, mock_client_class: MagicMock) -> None:
        from src.agent.tools.web import fetch_page_text

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.text = "<html><body><p>" + "word " * 2000 + "</p></body></html>"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()
        self._client_returning(mock_client_class, mock_response)

        text, error = fetch_page_text("https://example.com", max_chars=500)

        assert error is None
        assert text is not None
        assert len(text) < 600  # cap + truncation marker

    def test_returns_error_for_invalid_url(self) -> None:
        from src.agent.tools.web import fetch_page_text

        text, error = fetch_page_text("ftp://example.com/file")

        assert text is None
        assert error is not None

    @patch("src.agent.tools.web.httpx.Client")
    def test_returns_error_for_binary_content(self, mock_client_class: MagicMock) -> None:
        from src.agent.tools.web import fetch_page_text

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.content = b"%PDF-1.4"
        mock_response.raise_for_status = MagicMock()
        self._client_returning(mock_client_class, mock_response)

        text, error = fetch_page_text("https://example.com/doc.pdf")

        assert text is None
        assert error is not None
        assert "fetch_url" in error  # points the model at the right tool
