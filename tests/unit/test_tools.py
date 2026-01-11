"""Unit tests for src/agent/tools package."""

import base64
import json
from unittest.mock import MagicMock, patch

import httpx
from ddgs.exceptions import DDGSException
from google.genai import errors as genai_errors

# Import public API from the package
from src.agent.tools import (
    FETCHABLE_BINARY_TYPES,
    TOOLS,
    execute_code,
    fetch_url,
    generate_image,
    get_tools_for_request,
    is_code_sandbox_available,
    retrieve_file,
    set_conversation_context,
    web_search,
)

# Import internal helpers directly from submodules for testing
from src.agent.tools.code_execution import (
    _build_execution_response,
    _build_font_setup_code,
    _extract_plots,
    _get_mime_type,
    _needs_font_setup,
    _parse_output_files_from_stdout,
    _wrap_user_code,
)
from src.agent.tools.image_generation import VALID_ASPECT_RATIOS
from src.agent.tools.web import _get_content_type_category


class TestFetchUrl:
    """Tests for fetch_url tool."""

    @patch("src.agent.tools.web.httpx.Client")
    def test_fetches_html_content(self, mock_client_class: MagicMock) -> None:
        """Should fetch and extract text from HTML pages."""
        mock_response = MagicMock()
        mock_response.status_code = 200
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
        mock_client.get.assert_called_once_with("https://example.com")

    def test_rejects_invalid_url_scheme(self) -> None:
        """Should reject URLs without http/https scheme."""
        result = fetch_url.invoke({"url": "not-a-url"})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "Invalid URL" in parsed["error"]

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


class TestWebSearch:
    """Tests for web_search tool."""

    @patch("src.agent.tools.web.DDGS")
    def test_returns_search_results(self, mock_ddgs_class: MagicMock) -> None:
        """Should return formatted search results."""
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = [
            {"title": "Result 1", "href": "https://example.com/1", "body": "Snippet 1"},
            {"title": "Result 2", "href": "https://example.com/2", "body": "Snippet 2"},
        ]
        mock_ddgs_class.return_value = mock_ddgs

        result = web_search.invoke({"query": "test query"})
        parsed = json.loads(result)

        assert parsed["query"] == "test query"
        assert len(parsed["results"]) == 2
        assert parsed["results"][0]["title"] == "Result 1"
        assert parsed["results"][0]["url"] == "https://example.com/1"
        assert parsed["results"][0]["snippet"] == "Snippet 1"

    @patch("src.agent.tools.web.DDGS")
    def test_handles_empty_results(self, mock_ddgs_class: MagicMock) -> None:
        """Should handle no search results."""
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = []
        mock_ddgs_class.return_value = mock_ddgs

        result = web_search.invoke({"query": "obscure query xyz123"})
        parsed = json.loads(result)

        assert parsed["results"] == []
        assert "error" in parsed  # Should include error message

    @patch("src.agent.tools.web.DDGS")
    def test_respects_num_results_limit(self, mock_ddgs_class: MagicMock) -> None:
        """Should pass num_results to DDGS."""
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = []
        mock_ddgs_class.return_value = mock_ddgs

        web_search.invoke({"query": "test", "num_results": 3})

        mock_ddgs.text.assert_called_once_with("test", max_results=3)

    @patch("src.agent.tools.web.DDGS")
    def test_caps_num_results_at_10(self, mock_ddgs_class: MagicMock) -> None:
        """Should cap num_results at 10."""
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = []
        mock_ddgs_class.return_value = mock_ddgs

        web_search.invoke({"query": "test", "num_results": 100})

        mock_ddgs.text.assert_called_once_with("test", max_results=10)

    @patch("src.agent.tools.web.DDGS")
    def test_handles_search_exception(self, mock_ddgs_class: MagicMock) -> None:
        """Should handle exceptions gracefully."""
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.side_effect = DDGSException("Search failed")
        mock_ddgs_class.return_value = mock_ddgs

        result = web_search.invoke({"query": "test"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert parsed["results"] == []


class TestGenerateImage:
    """Tests for generate_image tool."""

    def test_rejects_empty_prompt(self) -> None:
        """Should reject empty prompts."""
        result = generate_image.invoke({"prompt": ""})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "empty" in parsed["error"].lower()

    def test_rejects_whitespace_only_prompt(self) -> None:
        """Should reject whitespace-only prompts."""
        result = generate_image.invoke({"prompt": "   "})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "empty" in parsed["error"].lower()

    def test_rejects_invalid_aspect_ratio(self) -> None:
        """Should reject invalid aspect ratios."""
        result = generate_image.invoke({"prompt": "test image", "aspect_ratio": "5:3"})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "Invalid aspect ratio" in parsed["error"]

    def test_valid_aspect_ratios_constant(self) -> None:
        """Verify valid aspect ratios are defined."""
        expected_ratios = {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"}
        assert VALID_ASPECT_RATIOS == expected_ratios

    @patch("src.agent.tools.image_generation.genai.Client")
    def test_successful_generation(self, mock_client_class: MagicMock) -> None:
        """Should return image data on successful generation."""
        # Mock the response structure
        mock_part = MagicMock()
        mock_part.inline_data = MagicMock()
        mock_part.inline_data.data = b"fake_image_data"
        mock_part.inline_data.mime_type = "image/png"

        mock_candidate = MagicMock()
        mock_candidate.content = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 20
        mock_response.usage_metadata.thoughts_token_count = 5
        mock_response.usage_metadata.total_token_count = 35

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = generate_image.invoke({"prompt": "A beautiful sunset"})
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "_full_result" in parsed
        assert "image" in parsed["_full_result"]
        assert "data" in parsed["_full_result"]["image"]

    @patch("src.agent.tools.image_generation.genai.Client")
    def test_includes_usage_metadata(self, mock_client_class: MagicMock) -> None:
        """Should include usage metadata for cost tracking."""
        mock_part = MagicMock()
        mock_part.inline_data = MagicMock()
        mock_part.inline_data.data = b"image"
        mock_part.inline_data.mime_type = "image/png"

        mock_candidate = MagicMock()
        mock_candidate.content = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 100
        mock_response.usage_metadata.candidates_token_count = 200
        mock_response.usage_metadata.thoughts_token_count = 50
        mock_response.usage_metadata.total_token_count = 350

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = generate_image.invoke({"prompt": "test"})
        parsed = json.loads(result)

        assert "usage_metadata" in parsed
        assert parsed["usage_metadata"]["prompt_token_count"] == 100
        assert parsed["usage_metadata"]["candidates_token_count"] == 200

    @patch("src.agent.tools.image_generation.genai.Client")
    def test_handles_no_candidates(self, mock_client_class: MagicMock) -> None:
        """Should return error when no candidates in response."""
        mock_response = MagicMock()
        mock_response.candidates = []
        mock_response.usage_metadata = None

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = generate_image.invoke({"prompt": "test"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "No image generated" in parsed["error"]

    @patch("src.agent.tools.image_generation.genai.Client")
    def test_handles_safety_block(self, mock_client_class: MagicMock) -> None:
        """Should return friendly error for safety blocks."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = genai_errors.ClientError(
            code=400, response_json={"error": {"message": "SAFETY: Content blocked"}}
        )
        mock_client_class.return_value = mock_client

        result = generate_image.invoke({"prompt": "inappropriate content"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "safety filters" in parsed["error"].lower()

    @patch("src.agent.tools.image_generation.Config.MAX_IMAGE_PROMPT_LENGTH", 100)
    def test_rejects_too_long_prompt(self) -> None:
        """Should reject prompts exceeding max length."""
        long_prompt = "a" * 150
        result = generate_image.invoke({"prompt": long_prompt})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "too long" in parsed["error"].lower()

    @patch("src.agent.tools.image_generation.genai.Client")
    @patch("src.agent.tools.image_generation.get_current_message_files")
    def test_reference_images_all(
        self, mock_get_files: MagicMock, mock_client_class: MagicMock
    ) -> None:
        """Should include all uploaded images when reference_images='all'."""
        # Mock uploaded files in context
        mock_get_files.return_value = [
            {"type": "image/png", "data": "base64data1", "name": "img1.png"},
            {"type": "image/jpeg", "data": "base64data2", "name": "img2.jpg"},
        ]

        # Mock successful generation response
        mock_part = MagicMock()
        mock_part.inline_data = MagicMock()
        mock_part.inline_data.data = b"output_image"
        mock_part.inline_data.mime_type = "image/png"

        mock_candidate = MagicMock()
        mock_candidate.content = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata = None

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = generate_image.invoke({"prompt": "Edit this image", "reference_images": "all"})
        parsed = json.loads(result)

        assert parsed["success"] is True
        # Verify generate_content was called with multimodal contents
        call_args = mock_client.models.generate_content.call_args
        contents = call_args.kwargs["contents"]
        assert isinstance(contents, list)
        assert contents[0] == "Edit this image"
        assert len(contents) == 3  # prompt + 2 images
        assert contents[1]["inline_data"]["data"] == "base64data1"
        assert contents[2]["inline_data"]["data"] == "base64data2"

    @patch("src.agent.tools.image_generation.genai.Client")
    @patch("src.agent.tools.image_generation.get_current_message_files")
    def test_reference_images_specific_index(
        self, mock_get_files: MagicMock, mock_client_class: MagicMock
    ) -> None:
        """Should include only specified images when using indices."""
        mock_get_files.return_value = [
            {"type": "image/png", "data": "base64data1", "name": "img1.png"},
            {"type": "image/jpeg", "data": "base64data2", "name": "img2.jpg"},
            {"type": "image/png", "data": "base64data3", "name": "img3.png"},
        ]

        mock_part = MagicMock()
        mock_part.inline_data = MagicMock()
        mock_part.inline_data.data = b"output_image"
        mock_part.inline_data.mime_type = "image/png"

        mock_candidate = MagicMock()
        mock_candidate.content = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata = None

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        # Test with index "0"
        result = generate_image.invoke({"prompt": "Edit first image", "reference_images": "0"})
        parsed = json.loads(result)

        assert parsed["success"] is True
        call_args = mock_client.models.generate_content.call_args
        contents = call_args.kwargs["contents"]
        assert len(contents) == 2  # prompt + 1 image
        assert contents[1]["inline_data"]["data"] == "base64data1"

    @patch("src.agent.tools.image_generation.genai.Client")
    @patch("src.agent.tools.image_generation.get_current_message_files")
    def test_reference_images_multiple_indices(
        self, mock_get_files: MagicMock, mock_client_class: MagicMock
    ) -> None:
        """Should include multiple specified images."""
        mock_get_files.return_value = [
            {"type": "image/png", "data": "base64data1", "name": "img1.png"},
            {"type": "image/jpeg", "data": "base64data2", "name": "img2.jpg"},
            {"type": "image/png", "data": "base64data3", "name": "img3.png"},
        ]

        mock_part = MagicMock()
        mock_part.inline_data = MagicMock()
        mock_part.inline_data.data = b"output_image"
        mock_part.inline_data.mime_type = "image/png"

        mock_candidate = MagicMock()
        mock_candidate.content = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata = None

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        # Test with indices "0,2"
        result = generate_image.invoke(
            {"prompt": "Combine these images", "reference_images": "0,2"}
        )
        parsed = json.loads(result)

        assert parsed["success"] is True
        call_args = mock_client.models.generate_content.call_args
        contents = call_args.kwargs["contents"]
        assert len(contents) == 3  # prompt + 2 images
        assert contents[1]["inline_data"]["data"] == "base64data1"
        assert contents[2]["inline_data"]["data"] == "base64data3"

    @patch("src.agent.tools.image_generation.genai.Client")
    @patch("src.agent.tools.image_generation.get_current_message_files")
    def test_reference_images_filters_non_images(
        self, mock_get_files: MagicMock, mock_client_class: MagicMock
    ) -> None:
        """Should filter out non-image files."""
        mock_get_files.return_value = [
            {"type": "text/plain", "data": "textdata", "name": "file.txt"},
            {"type": "image/png", "data": "imagedata", "name": "img.png"},
            {"type": "application/pdf", "data": "pdfdata", "name": "doc.pdf"},
        ]

        mock_part = MagicMock()
        mock_part.inline_data = MagicMock()
        mock_part.inline_data.data = b"output_image"
        mock_part.inline_data.mime_type = "image/png"

        mock_candidate = MagicMock()
        mock_candidate.content = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata = None

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = generate_image.invoke({"prompt": "Edit the image", "reference_images": "all"})
        parsed = json.loads(result)

        assert parsed["success"] is True
        call_args = mock_client.models.generate_content.call_args
        contents = call_args.kwargs["contents"]
        # Only the image should be included, not text or PDF
        assert len(contents) == 2  # prompt + 1 image
        assert contents[1]["inline_data"]["data"] == "imagedata"

    @patch("src.agent.tools.image_generation.genai.Client")
    @patch("src.agent.tools.image_generation.get_current_message_files")
    def test_reference_images_no_files_in_context(
        self, mock_get_files: MagicMock, mock_client_class: MagicMock
    ) -> None:
        """Should fall back to text-only when no files in context."""
        mock_get_files.return_value = None

        mock_part = MagicMock()
        mock_part.inline_data = MagicMock()
        mock_part.inline_data.data = b"output_image"
        mock_part.inline_data.mime_type = "image/png"

        mock_candidate = MagicMock()
        mock_candidate.content = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata = None

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = generate_image.invoke({"prompt": "Generate something", "reference_images": "all"})
        parsed = json.loads(result)

        # Should still succeed with text-only prompt
        assert parsed["success"] is True
        call_args = mock_client.models.generate_content.call_args
        contents = call_args.kwargs["contents"]
        # Falls back to list with just prompt when reference_images specified but no files
        assert contents == ["Generate something"]

    @patch("src.agent.tools.image_generation.genai.Client")
    @patch("src.agent.tools.image_generation.get_current_message_files")
    def test_reference_images_invalid_index_ignored(
        self, mock_get_files: MagicMock, mock_client_class: MagicMock
    ) -> None:
        """Should ignore invalid indices and use valid ones."""
        mock_get_files.return_value = [
            {"type": "image/png", "data": "imagedata", "name": "img.png"},
        ]

        mock_part = MagicMock()
        mock_part.inline_data = MagicMock()
        mock_part.inline_data.data = b"output_image"
        mock_part.inline_data.mime_type = "image/png"

        mock_candidate = MagicMock()
        mock_candidate.content = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata = None

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        # Index 5 doesn't exist, only index 0 should be used
        result = generate_image.invoke({"prompt": "Edit image", "reference_images": "0,5"})
        parsed = json.loads(result)

        assert parsed["success"] is True
        call_args = mock_client.models.generate_content.call_args
        contents = call_args.kwargs["contents"]
        assert len(contents) == 2  # prompt + 1 valid image


class TestGetMimeType:
    """Tests for _get_mime_type helper function."""

    def test_pdf_mime_type(self) -> None:
        """Should return correct MIME type for PDF."""
        assert _get_mime_type("report.pdf") == "application/pdf"

    def test_png_mime_type(self) -> None:
        """Should return correct MIME type for PNG."""
        assert _get_mime_type("image.png") == "image/png"

    def test_jpg_mime_type(self) -> None:
        """Should return correct MIME type for JPG."""
        assert _get_mime_type("photo.jpg") == "image/jpeg"
        assert _get_mime_type("photo.jpeg") == "image/jpeg"

    def test_csv_mime_type(self) -> None:
        """Should return correct MIME type for CSV."""
        assert _get_mime_type("data.csv") == "text/csv"

    def test_unknown_extension(self) -> None:
        """Should return octet-stream for unknown extensions."""
        assert _get_mime_type("file.xyz") == "application/octet-stream"

    def test_no_extension(self) -> None:
        """Should return octet-stream for files without extension."""
        assert _get_mime_type("filename") == "application/octet-stream"


class TestExecuteCode:
    """Tests for execute_code tool."""

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", False)
    def test_returns_error_when_disabled(self) -> None:
        """Should return error when sandbox is disabled."""
        result = execute_code.invoke({"code": "print('hello')"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "disabled" in parsed["error"].lower()

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=False)
    def test_returns_error_when_docker_unavailable(self, mock_check: MagicMock) -> None:
        """Should return error when Docker is not available."""
        result = execute_code.invoke({"code": "print('hello')"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "Docker" in parsed["error"] or "not available" in parsed["error"].lower()

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    def test_rejects_empty_code(self, mock_check: MagicMock) -> None:
        """Should reject empty code."""
        result = execute_code.invoke({"code": ""})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "empty" in parsed["error"].lower()

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    def test_rejects_whitespace_only_code(self, mock_check: MagicMock) -> None:
        """Should reject whitespace-only code."""
        result = execute_code.invoke({"code": "   "})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "empty" in parsed["error"].lower()

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    @patch("llm_sandbox.SandboxSession")
    def test_successful_execution(
        self, mock_session_class: MagicMock, mock_check: MagicMock
    ) -> None:
        """Should return success for valid code execution."""
        # Mock the sandbox session
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = "Hello, World!\n"
        mock_result.stderr = ""
        mock_result.plots = []

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = mock_result
        mock_session_class.return_value = mock_session

        result = execute_code.invoke({"code": "print('Hello, World!')"})
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["exit_code"] == 0
        assert "Hello, World!" in parsed["stdout"]

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    @patch("llm_sandbox.SandboxSession")
    def test_captures_stderr(self, mock_session_class: MagicMock, mock_check: MagicMock) -> None:
        """Should capture stderr from execution."""
        mock_result = MagicMock()
        mock_result.exit_code = 1
        mock_result.stdout = ""
        mock_result.stderr = "NameError: name 'undefined_var' is not defined"
        mock_result.plots = []

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = mock_result
        mock_session_class.return_value = mock_session

        result = execute_code.invoke({"code": "print(undefined_var)"})
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["exit_code"] == 1
        assert "NameError" in parsed["stderr"]

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    @patch("llm_sandbox.SandboxSession")
    def test_captures_plots(self, mock_session_class: MagicMock, mock_check: MagicMock) -> None:
        """Should capture matplotlib plots with metadata in response and data in _full_result."""
        mock_plot = MagicMock()
        mock_plot.format = MagicMock()
        mock_plot.format.value = "png"
        mock_plot.content_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.plots = [mock_plot]

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = mock_result
        mock_session_class.return_value = mock_session

        result = execute_code.invoke(
            {"code": "import matplotlib.pyplot as plt; plt.plot([1,2,3]); plt.show()"}
        )
        parsed = json.loads(result)

        assert parsed["success"] is True
        # LLM sees only metadata (no base64 data)
        assert "plots" in parsed
        assert len(parsed["plots"]) == 1
        assert parsed["plots"][0]["format"] == "png"
        assert parsed["plots"][0]["name"] == "plot_1.png"
        assert "data" not in parsed["plots"][0]  # Data is in _full_result

        # Full data is in _full_result for server-side extraction
        assert "_full_result" in parsed
        assert "files" in parsed["_full_result"]
        assert len(parsed["_full_result"]["files"]) == 1
        assert parsed["_full_result"]["files"][0]["name"] == "plot_1.png"
        assert parsed["_full_result"]["files"][0]["data"] == mock_plot.content_base64

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    @patch("llm_sandbox.SandboxSession")
    def test_output_files_uses_full_result_pattern(
        self, mock_session_class: MagicMock, mock_check: MagicMock
    ) -> None:
        """Should put file data in _full_result and only metadata in response."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = '__OUTPUT_FILES__:["report.pdf"]\n'
        mock_result.stderr = ""
        mock_result.plots = []

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = mock_result

        # Mock file extraction from sandbox
        def copy_from_runtime(src: str, dest: str) -> None:
            with open(dest, "wb") as f:
                f.write(b"PDF content here")

        mock_session.copy_from_runtime = copy_from_runtime
        mock_session_class.return_value = mock_session

        result = execute_code.invoke({"code": "generate_pdf()"})
        parsed = json.loads(result)

        assert parsed["success"] is True

        # LLM sees only metadata (filename, type, size - no data)
        assert "files" in parsed
        assert len(parsed["files"]) == 1
        assert parsed["files"][0]["name"] == "report.pdf"
        assert parsed["files"][0]["mime_type"] == "application/pdf"
        assert parsed["files"][0]["size"] == 16  # len(b"PDF content here")
        assert "data" not in parsed["files"][0]  # Data is NOT in the files list

        # Message for LLM to inform user
        assert "message" in parsed
        assert "report.pdf" in parsed["message"]

        # Full data is in _full_result for server-side extraction
        assert "_full_result" in parsed
        assert "files" in parsed["_full_result"]
        assert len(parsed["_full_result"]["files"]) == 1
        assert parsed["_full_result"]["files"][0]["name"] == "report.pdf"
        assert "data" in parsed["_full_result"]["files"][0]  # Data IS here

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    @patch("llm_sandbox.SandboxSession")
    def test_handles_timeout(self, mock_session_class: MagicMock, mock_check: MagicMock) -> None:
        """Should handle execution timeout."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.side_effect = TimeoutError("Execution timed out")
        mock_session_class.return_value = mock_session

        result = execute_code.invoke({"code": "while True: pass"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "timed out" in parsed["error"].lower()

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    @patch("llm_sandbox.SandboxSession")
    def test_handles_docker_error(
        self, mock_session_class: MagicMock, mock_check: MagicMock
    ) -> None:
        """Should handle Docker connection errors gracefully."""
        mock_session_class.side_effect = Exception("Cannot connect to Docker daemon")

        result = execute_code.invoke({"code": "print('test')"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "Docker" in parsed["error"] or "failed" in parsed["error"].lower()


class TestIsCodeSandboxAvailable:
    """Tests for is_code_sandbox_available function."""

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", False)
    def test_returns_false_when_disabled(self) -> None:
        """Should return False when sandbox is disabled in config."""
        assert is_code_sandbox_available() is False

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=False)
    def test_returns_false_when_docker_unavailable(self, mock_check: MagicMock) -> None:
        """Should return False when Docker is not available."""
        assert is_code_sandbox_available() is False

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    def test_returns_true_when_available(self, mock_check: MagicMock) -> None:
        """Should return True when sandbox is enabled and Docker is available."""
        assert is_code_sandbox_available() is True


# ============================================================================
# Tests for Code Execution Helper Functions
# ============================================================================


class TestBuildFontSetupCode:
    """Tests for _build_font_setup_code helper function."""

    def test_returns_font_installation_code(self) -> None:
        """Should return code that installs DejaVu fonts."""
        result = _build_font_setup_code()
        assert "apt-get" in result
        assert "fonts-dejavu-core" in result

    def test_includes_helper_function(self) -> None:
        """Should include _get_dejavu_font helper function."""
        result = _build_font_setup_code()
        assert "def _get_dejavu_font()" in result
        assert "DejaVuSans.ttf" in result

    def test_uses_quiet_mode(self) -> None:
        """Should use quiet mode for apt-get to reduce output."""
        result = _build_font_setup_code()
        assert "-qq" in result


class TestNeedsFontSetup:
    """Tests for _needs_font_setup helper function."""

    def test_detects_fpdf_lowercase(self) -> None:
        """Should detect fpdf import in lowercase."""
        assert _needs_font_setup("from fpdf import FPDF") is True

    def test_detects_fpdf_uppercase(self) -> None:
        """Should detect FPDF class name."""
        assert _needs_font_setup("pdf = FPDF()") is True

    def test_detects_fpdf_in_comment(self) -> None:
        """Should detect fpdf even in comments (conservative approach)."""
        assert _needs_font_setup("# using fpdf for PDF") is True

    def test_returns_false_for_no_fpdf(self) -> None:
        """Should return False when code doesn't use fpdf."""
        assert _needs_font_setup("print('hello world')") is False

    def test_returns_false_for_reportlab(self) -> None:
        """Should return False for reportlab (uses different font system)."""
        assert _needs_font_setup("from reportlab.lib.pagesizes import letter") is False


class TestWrapUserCode:
    """Tests for _wrap_user_code helper function."""

    def test_creates_output_directory(self) -> None:
        """Should create /output directory at start."""
        result = _wrap_user_code("print('test')")
        assert "os.makedirs('/output', exist_ok=True)" in result

    def test_includes_user_code(self) -> None:
        """Should include the user's code."""
        user_code = "x = 1 + 1\nprint(x)"
        result = _wrap_user_code(user_code)
        assert user_code in result

    def test_adds_file_listing(self) -> None:
        """Should add code to list output files."""
        result = _wrap_user_code("print('test')")
        assert "__OUTPUT_FILES__" in result
        assert "os.listdir('/output')" in result

    def test_includes_font_setup_for_fpdf(self) -> None:
        """Should include font setup when fpdf is used."""
        result = _wrap_user_code("from fpdf import FPDF")
        assert "fonts-dejavu-core" in result
        assert "_get_dejavu_font" in result

    def test_excludes_font_setup_for_non_fpdf(self) -> None:
        """Should not include font setup for non-fpdf code."""
        result = _wrap_user_code("import numpy as np")
        assert "fonts-dejavu-core" not in result


class TestParseOutputFilesFromStdout:
    """Tests for _parse_output_files_from_stdout helper function."""

    def test_extracts_single_file(self) -> None:
        """Should extract a single file from stdout."""
        stdout = 'Some output\n__OUTPUT_FILES__:["report.pdf"]\n'
        files, clean = _parse_output_files_from_stdout(stdout)
        assert files == ["report.pdf"]
        assert "__OUTPUT_FILES__" not in clean

    def test_extracts_multiple_files(self) -> None:
        """Should extract multiple files from stdout."""
        stdout = '__OUTPUT_FILES__:["file1.txt", "file2.png", "file3.pdf"]\n'
        files, clean = _parse_output_files_from_stdout(stdout)
        assert files == ["file1.txt", "file2.png", "file3.pdf"]

    def test_preserves_other_output(self) -> None:
        """Should preserve stdout content that's not the marker."""
        stdout = "Hello World\nCalculation result: 42\n__OUTPUT_FILES__:[]\n"
        files, clean = _parse_output_files_from_stdout(stdout)
        assert "Hello World" in clean
        assert "Calculation result: 42" in clean
        assert "__OUTPUT_FILES__" not in clean

    def test_handles_no_marker(self) -> None:
        """Should handle stdout without the marker."""
        stdout = "Just some regular output\n"
        files, clean = _parse_output_files_from_stdout(stdout)
        assert files == []
        assert "Just some regular output" in clean

    def test_handles_invalid_json(self) -> None:
        """Should handle malformed JSON gracefully."""
        stdout = "__OUTPUT_FILES__:not valid json\n"
        files, clean = _parse_output_files_from_stdout(stdout)
        assert files == []

    def test_handles_empty_stdout(self) -> None:
        """Should handle empty stdout."""
        files, clean = _parse_output_files_from_stdout("")
        assert files == []
        assert clean == ""


class TestExtractPlots:
    """Tests for _extract_plots helper function."""

    def test_extracts_single_plot(self) -> None:
        """Should extract a single matplotlib plot."""
        mock_plot = MagicMock()
        mock_plot.format = MagicMock()
        mock_plot.format.value = "png"
        mock_plot.content_base64 = "iVBORw0KGgo="

        mock_result = MagicMock()
        mock_result.plots = [mock_plot]

        full_plots, metadata = _extract_plots(mock_result)

        assert len(full_plots) == 1
        assert full_plots[0]["name"] == "plot_1.png"
        assert full_plots[0]["data"] == "iVBORw0KGgo="
        assert full_plots[0]["mime_type"] == "image/png"

        assert len(metadata) == 1
        assert metadata[0]["name"] == "plot_1.png"
        assert metadata[0]["format"] == "png"

    def test_extracts_multiple_plots(self) -> None:
        """Should extract multiple plots with sequential names."""
        mock_plot1 = MagicMock()
        mock_plot1.format = MagicMock()
        mock_plot1.format.value = "png"
        mock_plot1.content_base64 = "aGVsbG8="  # Valid base64 for "hello"

        mock_plot2 = MagicMock()
        mock_plot2.format = MagicMock()
        mock_plot2.format.value = "jpeg"
        mock_plot2.content_base64 = "d29ybGQ="  # Valid base64 for "world"

        mock_result = MagicMock()
        mock_result.plots = [mock_plot1, mock_plot2]

        full_plots, metadata = _extract_plots(mock_result)

        assert len(full_plots) == 2
        assert full_plots[0]["name"] == "plot_1.png"
        assert full_plots[1]["name"] == "plot_2.jpeg"

    def test_handles_no_plots(self) -> None:
        """Should handle result with no plots."""
        mock_result = MagicMock()
        mock_result.plots = []

        full_plots, metadata = _extract_plots(mock_result)

        assert full_plots == []
        assert metadata == []

    def test_handles_missing_plots_attribute(self) -> None:
        """Should handle result without plots attribute."""
        mock_result = MagicMock(spec=[])  # No attributes

        full_plots, metadata = _extract_plots(mock_result)

        assert full_plots == []
        assert metadata == []

    def test_handles_string_format(self) -> None:
        """Should handle format as string instead of enum."""
        mock_plot = MagicMock()
        mock_plot.format = "svg"  # String, not enum
        mock_plot.content_base64 = "c3ZnX2RhdGE="  # Valid base64 for "svg_data"

        mock_result = MagicMock()
        mock_result.plots = [mock_plot]

        full_plots, metadata = _extract_plots(mock_result)

        assert full_plots[0]["name"] == "plot_1.svg"
        assert full_plots[0]["mime_type"] == "image/svg"


class TestBuildExecutionResponse:
    """Tests for _build_execution_response helper function."""

    def test_builds_success_response(self) -> None:
        """Should build response for successful execution."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stderr = ""

        response = _build_execution_response(
            result=mock_result,
            clean_stdout="Hello World",
            file_metadata=[],
            plot_metadata=[],
            full_result_files=[],
        )

        assert response["success"] is True
        assert response["exit_code"] == 0
        assert response["stdout"] == "Hello World"
        assert response["stderr"] == ""

    def test_builds_failure_response(self) -> None:
        """Should build response for failed execution."""
        mock_result = MagicMock()
        mock_result.exit_code = 1
        mock_result.stderr = "Error: something went wrong"

        response = _build_execution_response(
            result=mock_result,
            clean_stdout="",
            file_metadata=[],
            plot_metadata=[],
            full_result_files=[],
        )

        assert response["success"] is False
        assert response["exit_code"] == 1
        assert response["stderr"] == "Error: something went wrong"

    def test_includes_file_metadata(self) -> None:
        """Should include file metadata in response."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stderr = ""

        file_metadata = [
            {"name": "report.pdf", "mime_type": "application/pdf", "size": 1024},
        ]

        response = _build_execution_response(
            result=mock_result,
            clean_stdout="",
            file_metadata=file_metadata,
            plot_metadata=[],
            full_result_files=[],
        )

        assert "files" in response
        assert response["files"] == file_metadata
        assert "message" in response
        assert "report.pdf" in response["message"]

    def test_includes_plot_metadata(self) -> None:
        """Should include plot metadata in response."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stderr = ""

        plot_metadata = [{"format": "png", "name": "plot_1.png"}]

        response = _build_execution_response(
            result=mock_result,
            clean_stdout="",
            file_metadata=[],
            plot_metadata=plot_metadata,
            full_result_files=[],
        )

        assert "plots" in response
        assert response["plots"] == plot_metadata

    def test_includes_full_result_files(self) -> None:
        """Should include _full_result with file data."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stderr = ""

        full_files = [{"name": "report.pdf", "data": "base64data", "size": 1024}]

        response = _build_execution_response(
            result=mock_result,
            clean_stdout="",
            file_metadata=[],
            plot_metadata=[],
            full_result_files=full_files,
        )

        assert "_full_result" in response
        assert response["_full_result"]["files"] == full_files

    def test_omits_empty_sections(self) -> None:
        """Should not include files/plots keys when empty."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stderr = ""

        response = _build_execution_response(
            result=mock_result,
            clean_stdout="output",
            file_metadata=[],
            plot_metadata=[],
            full_result_files=[],
        )

        assert "files" not in response
        assert "plots" not in response
        assert "_full_result" not in response
        assert "message" not in response

    def test_handles_none_stderr(self) -> None:
        """Should handle None stderr gracefully."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stderr = None

        response = _build_execution_response(
            result=mock_result,
            clean_stdout="",
            file_metadata=[],
            plot_metadata=[],
            full_result_files=[],
        )

        assert response["stderr"] == ""


# ============================================================================
# Tests for File Retrieval Tool
# ============================================================================


class TestRetrieveFile:
    """Tests for retrieve_file tool."""

    def test_returns_error_without_context(self) -> None:
        """Should return error when no conversation context is set."""
        set_conversation_context(None, None)
        result = retrieve_file.invoke({"list_files": True})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "No conversation context" in parsed["error"]

    @patch("src.db.models.db")
    def test_returns_error_for_unauthorized_conversation(self, mock_db: MagicMock) -> None:
        """Should return error when user doesn't own conversation."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = None

        result = retrieve_file.invoke({"list_files": True})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "not authorized" in parsed["error"]
        set_conversation_context(None, None)

    @patch("src.db.models.db")
    def test_lists_files_in_conversation(self, mock_db: MagicMock) -> None:
        """Should list all files in conversation."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()

        # Mock messages with files
        mock_msg1 = MagicMock()
        mock_msg1.id = "msg-1"
        mock_msg1.files = [
            {"name": "photo.jpg", "type": "image/jpeg", "size": 1000},
        ]
        mock_msg1.role = MagicMock(value="user")

        mock_msg2 = MagicMock()
        mock_msg2.id = "msg-2"
        mock_msg2.files = [
            {"name": "result.png", "type": "image/png", "size": 2000},
        ]
        mock_msg2.role = MagicMock(value="assistant")

        mock_msg3 = MagicMock()
        mock_msg3.id = "msg-3"
        mock_msg3.files = []  # No files
        mock_msg3.role = MagicMock(value="user")

        mock_db.get_messages.return_value = [mock_msg1, mock_msg2, mock_msg3]

        result = retrieve_file.invoke({"list_files": True})
        parsed = json.loads(result)

        assert parsed["count"] == 2
        assert len(parsed["files"]) == 2
        assert parsed["files"][0]["message_id"] == "msg-1"
        assert parsed["files"][0]["name"] == "photo.jpg"
        assert parsed["files"][0]["role"] == "user"
        assert parsed["files"][1]["message_id"] == "msg-2"
        assert parsed["files"][1]["name"] == "result.png"
        assert parsed["files"][1]["role"] == "assistant"

        set_conversation_context(None, None)

    @patch("src.db.models.db")
    def test_lists_empty_files(self, mock_db: MagicMock) -> None:
        """Should return empty list when no files in conversation."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()

        mock_msg = MagicMock()
        mock_msg.files = []
        mock_msg.role = MagicMock(value="user")
        mock_db.get_messages.return_value = [mock_msg]

        result = retrieve_file.invoke({"list_files": True})
        parsed = json.loads(result)

        assert parsed["count"] == 0
        assert parsed["files"] == []
        assert "No files found" in parsed["message"]

        set_conversation_context(None, None)

    @patch("src.db.models.db")
    def test_requires_message_id_for_retrieval(self, mock_db: MagicMock) -> None:
        """Should require message_id when not listing files."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()

        result = retrieve_file.invoke({})  # No message_id
        parsed = json.loads(result)

        assert "error" in parsed
        assert "message_id is required" in parsed["error"]

        set_conversation_context(None, None)

    @patch("src.db.models.db")
    def test_returns_error_for_nonexistent_message(self, mock_db: MagicMock) -> None:
        """Should return error when message doesn't exist."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()
        mock_db.get_message_by_id.return_value = None

        result = retrieve_file.invoke({"message_id": "msg-999"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "Message not found" in parsed["error"]

        set_conversation_context(None, None)

    @patch("src.db.models.db")
    def test_returns_error_for_wrong_conversation(self, mock_db: MagicMock) -> None:
        """Should return error when message belongs to different conversation."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()

        mock_message = MagicMock()
        mock_message.conversation_id = "conv-different"
        mock_db.get_message_by_id.return_value = mock_message

        result = retrieve_file.invoke({"message_id": "msg-1"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "does not belong to this conversation" in parsed["error"]

        set_conversation_context(None, None)

    @patch("src.db.models.db")
    def test_returns_error_for_invalid_file_index(self, mock_db: MagicMock) -> None:
        """Should return error when file index is out of bounds."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()

        mock_message = MagicMock()
        mock_message.conversation_id = "conv-123"
        mock_message.files = [{"name": "only_one.jpg"}]
        mock_db.get_message_by_id.return_value = mock_message

        result = retrieve_file.invoke({"message_id": "msg-1", "file_index": 5})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "File index 5 not found" in parsed["error"]
        assert "has 1 file(s)" in parsed["error"]

        set_conversation_context(None, None)

    @patch("src.db.blob_store.get_blob_store")
    @patch("src.db.models.db")
    def test_retrieves_image_as_multimodal(
        self, mock_db: MagicMock, mock_get_blob_store: MagicMock
    ) -> None:
        """Should return image as multimodal content."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()

        mock_message = MagicMock()
        mock_message.conversation_id = "conv-123"
        mock_message.files = [{"name": "photo.jpg", "type": "image/jpeg", "size": 1000}]
        mock_db.get_message_by_id.return_value = mock_message

        # Mock blob store
        mock_blob_store = MagicMock()
        mock_blob_store.get.return_value = (b"fake_image_data", "image/jpeg")
        mock_get_blob_store.return_value = mock_blob_store

        result = retrieve_file.invoke({"message_id": "msg-1", "file_index": 0})

        # Should return multimodal content
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["type"] == "text"
        assert "photo.jpg" in result[0]["text"]
        assert result[1]["type"] == "image"
        assert result[1]["mime_type"] == "image/jpeg"
        assert result[1]["base64"] == base64.b64encode(b"fake_image_data").decode("utf-8")

        set_conversation_context(None, None)

    @patch("src.db.blob_store.get_blob_store")
    @patch("src.db.models.db")
    def test_retrieves_text_file_as_text(
        self, mock_db: MagicMock, mock_get_blob_store: MagicMock
    ) -> None:
        """Should return text file content as plain text."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()

        mock_message = MagicMock()
        mock_message.conversation_id = "conv-123"
        mock_message.files = [{"name": "data.txt", "type": "text/plain", "size": 100}]
        mock_db.get_message_by_id.return_value = mock_message

        # Mock blob store
        mock_blob_store = MagicMock()
        mock_blob_store.get.return_value = (b"Hello, world!", "text/plain")
        mock_get_blob_store.return_value = mock_blob_store

        result = retrieve_file.invoke({"message_id": "msg-1", "file_index": 0})

        # Should return text content as string
        assert isinstance(result, str)
        assert "Hello, world!" in result
        assert "data.txt" in result

        set_conversation_context(None, None)

    @patch("src.db.blob_store.get_blob_store")
    @patch("src.db.models.db")
    def test_falls_back_to_legacy_data(
        self, mock_db: MagicMock, mock_get_blob_store: MagicMock
    ) -> None:
        """Should fall back to legacy base64 data when blob store returns None."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()

        # Legacy data in message
        legacy_data = base64.b64encode(b"legacy_image_data").decode("utf-8")
        mock_message = MagicMock()
        mock_message.conversation_id = "conv-123"
        mock_message.files = [{"name": "old_photo.jpg", "type": "image/jpeg", "data": legacy_data}]
        mock_db.get_message_by_id.return_value = mock_message

        # Blob store returns None
        mock_blob_store = MagicMock()
        mock_blob_store.get.return_value = None
        mock_get_blob_store.return_value = mock_blob_store

        result = retrieve_file.invoke({"message_id": "msg-1", "file_index": 0})

        assert isinstance(result, list)
        assert result[1]["base64"] == legacy_data

        set_conversation_context(None, None)

    @patch("src.db.blob_store.get_blob_store")
    @patch("src.db.models.db")
    def test_returns_error_when_no_data_available(
        self, mock_db: MagicMock, mock_get_blob_store: MagicMock
    ) -> None:
        """Should return error when neither blob store nor legacy data is available."""
        set_conversation_context("conv-123", "user-456")
        mock_db.get_conversation.return_value = MagicMock()

        mock_message = MagicMock()
        mock_message.conversation_id = "conv-123"
        mock_message.files = [
            {"name": "missing.jpg", "type": "image/jpeg"}  # No "data" key
        ]
        mock_db.get_message_by_id.return_value = mock_message

        # Blob store returns None
        mock_blob_store = MagicMock()
        mock_blob_store.get.return_value = None
        mock_get_blob_store.return_value = mock_blob_store

        result = retrieve_file.invoke({"message_id": "msg-1", "file_index": 0})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "not found in storage" in parsed["error"]

        set_conversation_context(None, None)


# ============================================================================
# Tests for Todoist Tool
# ============================================================================


class TestTodoistTool:
    """Tests for todoist tool."""

    @patch("src.agent.tools.todoist._get_todoist_token")
    def test_returns_error_when_not_connected(self, mock_get_token: MagicMock) -> None:
        """Should return error when Todoist is not connected."""
        from src.agent.tools import todoist

        mock_get_token.return_value = None

        result = todoist.invoke({"action": "list_tasks"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "not connected" in parsed["error"].lower()

    @patch("src.agent.tools.todoist._get_todoist_token")
    def test_returns_error_for_unknown_action(self, mock_get_token: MagicMock) -> None:
        """Should return error for unknown action."""
        from src.agent.tools import todoist

        mock_get_token.return_value = "valid-token"

        result = todoist.invoke({"action": "unknown_action"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "Unknown action" in parsed["error"]

    @patch("src.agent.tools.todoist._get_todoist_token")
    @patch("src.agent.tools.todoist._todoist_api_request")
    def test_list_tasks_success(self, mock_api: MagicMock, mock_get_token: MagicMock) -> None:
        """Should successfully list tasks."""
        from src.agent.tools import todoist

        mock_get_token.return_value = "valid-token"
        mock_api.return_value = [
            {
                "id": "task-1",
                "content": "Test task",
                "project_id": "proj-1",
                "section_id": None,
                "priority": 1,
                "due": None,
            }
        ]

        result = todoist.invoke({"action": "list_tasks"})
        parsed = json.loads(result)

        assert "tasks" in parsed
        assert len(parsed["tasks"]) == 1
        assert parsed["tasks"][0]["id"] == "task-1"

    @patch("src.agent.tools.todoist._get_todoist_token")
    @patch("src.agent.tools.todoist._todoist_api_request")
    def test_add_task_success(self, mock_api: MagicMock, mock_get_token: MagicMock) -> None:
        """Should successfully add a task."""
        from src.agent.tools import todoist

        mock_get_token.return_value = "valid-token"
        mock_api.return_value = {
            "id": "new-task-1",
            "content": "New task",
        }

        result = todoist.invoke(
            {
                "action": "add_task",
                "content": "New task",
                "due_string": "tomorrow",
            }
        )
        parsed = json.loads(result)

        assert parsed["action"] == "add_task"
        assert parsed["success"] is True

    @patch("src.agent.tools.todoist._get_todoist_token")
    @patch("src.agent.tools.todoist._todoist_api_request")
    def test_complete_task_success(self, mock_api: MagicMock, mock_get_token: MagicMock) -> None:
        """Should successfully complete a task."""
        from src.agent.tools import todoist

        mock_get_token.return_value = "valid-token"
        mock_api.return_value = {}  # Close endpoint returns empty

        result = todoist.invoke(
            {
                "action": "complete_task",
                "task_id": "task-123",
            }
        )
        parsed = json.loads(result)

        assert parsed["action"] == "complete_task"
        assert parsed["success"] is True


# ============================================================================
# Tests for Google Calendar Tool
# ============================================================================


class TestGoogleCalendarTool:
    """Tests for google_calendar tool."""

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "")
    def test_returns_error_when_not_configured(self) -> None:
        """Should return error when Google Calendar is not configured."""
        from src.agent.tools import google_calendar

        result = google_calendar.invoke({"action": "list_calendars"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "not configured" in parsed["error"].lower()

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "test-id")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
    @patch("src.agent.tools.google_calendar._get_google_calendar_access_token")
    def test_returns_error_when_not_connected(self, mock_get_token: MagicMock) -> None:
        """Should return error when Google Calendar is not connected."""
        from src.agent.tools import google_calendar

        mock_get_token.return_value = None

        result = google_calendar.invoke({"action": "list_calendars"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "not connected" in parsed["error"].lower()

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "test-id")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
    @patch("src.agent.tools.google_calendar._get_google_calendar_access_token")
    def test_returns_error_for_unknown_action(self, mock_get_token: MagicMock) -> None:
        """Should return error for unknown action."""
        from src.agent.tools import google_calendar

        mock_get_token.return_value = ("valid-token", "user@example.com")

        result = google_calendar.invoke({"action": "unknown_action"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "Unknown action" in parsed["error"]

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "test-id")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
    @patch("src.agent.tools.google_calendar._get_google_calendar_access_token")
    @patch("src.agent.tools.google_calendar._google_calendar_api_request")
    def test_list_calendars_success(self, mock_api: MagicMock, mock_get_token: MagicMock) -> None:
        """Should successfully list calendars."""
        from src.agent.tools import google_calendar

        mock_get_token.return_value = ("valid-token", "user@example.com")
        mock_api.return_value = {
            "items": [
                {"id": "primary", "summary": "Main Calendar"},
                {"id": "work", "summary": "Work Calendar"},
            ]
        }

        result = google_calendar.invoke({"action": "list_calendars"})
        parsed = json.loads(result)

        assert "calendars" in parsed
        assert len(parsed["calendars"]) == 2

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "test-id")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
    @patch("src.agent.tools.google_calendar._get_google_calendar_access_token")
    @patch("src.agent.tools.google_calendar._google_calendar_api_request")
    def test_list_events_success(self, mock_api: MagicMock, mock_get_token: MagicMock) -> None:
        """Should successfully list events."""
        from src.agent.tools import google_calendar

        mock_get_token.return_value = ("valid-token", "user@example.com")
        mock_api.return_value = {
            "items": [
                {
                    "id": "evt-1",
                    "summary": "Team Meeting",
                    "start": {"dateTime": "2024-01-15T10:00:00Z"},
                    "end": {"dateTime": "2024-01-15T11:00:00Z"},
                }
            ]
        }

        result = google_calendar.invoke(
            {
                "action": "list_events",
                "calendar_id": "primary",
            }
        )
        parsed = json.loads(result)

        assert "events" in parsed
        assert len(parsed["events"]) == 1
        assert parsed["events"][0]["summary"] == "Team Meeting"

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "test-id")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
    @patch("src.agent.tools.google_calendar._get_google_calendar_access_token")
    @patch("src.agent.tools.google_calendar._google_calendar_api_request")
    def test_create_event_success(self, mock_api: MagicMock, mock_get_token: MagicMock) -> None:
        """Should successfully create an event."""
        from src.agent.tools import google_calendar

        mock_get_token.return_value = ("valid-token", "user@example.com")
        mock_api.return_value = {
            "id": "new-evt-1",
            "summary": "New Meeting",
            "start": {"dateTime": "2024-01-16T14:00:00Z"},
            "end": {"dateTime": "2024-01-16T15:00:00Z"},
        }

        result = google_calendar.invoke(
            {
                "action": "create_event",
                "summary": "New Meeting",
                "start_time": "2024-01-16T14:00:00Z",
                "end_time": "2024-01-16T15:00:00Z",
            }
        )
        parsed = json.loads(result)

        assert "event" in parsed
        assert parsed["event"]["summary"] == "New Meeting"

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "test-id")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
    @patch("src.agent.tools.google_calendar._get_google_calendar_access_token")
    @patch("src.agent.tools.google_calendar._google_calendar_api_request")
    def test_delete_event_success(self, mock_api: MagicMock, mock_get_token: MagicMock) -> None:
        """Should successfully delete an event."""
        from src.agent.tools import google_calendar

        mock_get_token.return_value = ("valid-token", "user@example.com")
        mock_api.return_value = {}  # Delete returns empty

        result = google_calendar.invoke(
            {
                "action": "delete_event",
                "event_id": "evt-123",
            }
        )
        parsed = json.loads(result)

        assert "action" in parsed
        assert parsed["action"] == "delete_event"

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "test-id")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
    @patch("src.agent.tools.google_calendar._get_google_calendar_access_token")
    def test_get_event_requires_event_id(self, mock_get_token: MagicMock) -> None:
        """Should require event_id for get_event action."""
        from src.agent.tools import google_calendar

        mock_get_token.return_value = ("valid-token", "user@example.com")

        result = google_calendar.invoke(
            {
                "action": "get_event",
                # Missing event_id
            }
        )
        parsed = json.loads(result)

        assert "error" in parsed
        assert "event_id" in parsed["error"].lower()

    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_ID", "test-id")
    @patch("src.agent.tools.google_calendar.Config.GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
    @patch("src.agent.tools.google_calendar._get_google_calendar_access_token")
    def test_respond_event_requires_response_status(self, mock_get_token: MagicMock) -> None:
        """Should require response_status for respond_event action."""
        from src.agent.tools import google_calendar

        mock_get_token.return_value = ("valid-token", "user@example.com")

        result = google_calendar.invoke(
            {
                "action": "respond_event",
                "event_id": "evt-123",
                # Missing response_status
            }
        )
        parsed = json.loads(result)

        assert "error" in parsed
        assert "response_status" in parsed["error"].lower()


class TestGetToolsForRequest:
    """Tests for get_tools_for_request function."""

    def test_returns_all_tools_by_default(self) -> None:
        """Should return all tools when anonymous_mode is False."""
        tools = get_tools_for_request(anonymous_mode=False)
        assert tools == TOOLS
        # Core tools should always be present
        tool_names = {t.name for t in tools}
        assert "web_search" in tool_names
        assert "fetch_url" in tool_names
        assert "generate_image" in tool_names
        assert "retrieve_file" in tool_names

    def test_excludes_integration_tools_in_anonymous_mode(self) -> None:
        """Should exclude todoist and google_calendar in anonymous mode."""
        tools = get_tools_for_request(anonymous_mode=True)
        tool_names = {t.name for t in tools}

        # Integration tools should be excluded (even if they were available)
        assert "todoist" not in tool_names
        assert "google_calendar" not in tool_names

        # Core tools should still be present
        assert "web_search" in tool_names
        assert "fetch_url" in tool_names
        assert "generate_image" in tool_names
        assert "retrieve_file" in tool_names

    def test_returns_fewer_or_same_tools_in_anonymous_mode(self) -> None:
        """Should return same or fewer tools in anonymous mode.

        Note: The exact count depends on whether integration tools are configured.
        If Todoist and Google Calendar are not configured, both modes return the same tools.
        If they are configured, anonymous mode returns 2 fewer tools.
        """
        normal_tools = get_tools_for_request(anonymous_mode=False)
        anonymous_tools = get_tools_for_request(anonymous_mode=True)

        # Anonymous mode should have same or fewer tools
        assert len(anonymous_tools) <= len(normal_tools)

        # Count how many integration tools are actually configured
        normal_tool_names = {t.name for t in normal_tools}
        integration_tools_available = len({"todoist", "google_calendar"} & normal_tool_names)

        # Should be exactly this many fewer
        assert len(anonymous_tools) == len(normal_tools) - integration_tools_available

    def test_default_parameter_is_false(self) -> None:
        """Should default to anonymous_mode=False."""
        tools = get_tools_for_request()
        assert tools == TOOLS
