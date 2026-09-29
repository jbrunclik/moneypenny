"""Unit tests for the generate_image tool (src/agent/tools/image_generation.py)."""

import json
from unittest.mock import MagicMock, patch

from google.genai import errors as genai_errors

from src.agent.tools import generate_image
from src.agent.tools.image_generation import VALID_ASPECT_RATIOS


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
        expected_ratios = {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "4:5", "5:4", "21:9"}
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
    def test_usage_metadata_splits_image_output_tokens(self, mock_client_class: MagicMock) -> None:
        """Image-modality output tokens are reported separately (billed at a higher rate)."""
        from google.genai import types

        mock_part = MagicMock()
        mock_part.inline_data = MagicMock()
        mock_part.inline_data.data = b"image"
        mock_part.inline_data.mime_type = "image/png"

        mock_candidate = MagicMock()
        mock_candidate.content = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=8,
            candidates_token_count=1177,
            candidates_tokens_details=[
                types.ModalityTokenCount(modality=types.MediaModality.IMAGE, token_count=1120)
            ],
            thoughts_token_count=82,
            total_token_count=1267,
        )

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        parsed = json.loads(generate_image.invoke({"prompt": "test"}))

        assert parsed["usage_metadata"]["candidates_token_count"] == 1177
        assert parsed["usage_metadata"]["image_output_token_count"] == 1120

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


def _mock_image_client(mock_client_class: MagicMock) -> MagicMock:
    """Wire a genai.Client mock that returns a single generated image."""
    mock_part = MagicMock()
    mock_part.inline_data = MagicMock()
    mock_part.inline_data.data = b"output_image"
    mock_part.inline_data.mime_type = "image/jpeg"
    mock_candidate = MagicMock()
    mock_candidate.content = MagicMock()
    mock_candidate.content.parts = [mock_part]
    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_response.usage_metadata = None
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_client_class.return_value = mock_client
    return mock_client


class TestGenerateImageOptions:
    """Tests for image_size and use_search options of generate_image."""

    @patch("src.agent.tools.image_generation.genai.Client")
    def test_default_image_size_is_1k(self, mock_client_class: MagicMock) -> None:
        mock_client = _mock_image_client(mock_client_class)
        generate_image.invoke({"prompt": "test"})
        config = mock_client.models.generate_content.call_args.kwargs["config"]
        assert config.image_config.image_size == "1K"

    @patch("src.agent.tools.image_generation.genai.Client")
    def test_image_size_passed_to_api(self, mock_client_class: MagicMock) -> None:
        mock_client = _mock_image_client(mock_client_class)
        parsed = json.loads(generate_image.invoke({"prompt": "test", "image_size": "4K"}))
        assert parsed["success"] is True
        config = mock_client.models.generate_content.call_args.kwargs["config"]
        assert config.image_config.image_size == "4K"

    @patch("src.agent.tools.image_generation.genai.Client")
    def test_image_size_is_case_insensitive(self, mock_client_class: MagicMock) -> None:
        """The API rejects lowercase 'k'; the tool normalizes it."""
        mock_client = _mock_image_client(mock_client_class)
        generate_image.invoke({"prompt": "test", "image_size": "2k"})
        config = mock_client.models.generate_content.call_args.kwargs["config"]
        assert config.image_config.image_size == "2K"

    def test_rejects_invalid_image_size(self) -> None:
        parsed = json.loads(generate_image.invoke({"prompt": "test", "image_size": "8K"}))
        assert "Invalid image size" in parsed["error"]

    @patch("src.agent.tools.image_generation.genai.Client")
    def test_search_grounding_off_by_default(self, mock_client_class: MagicMock) -> None:
        mock_client = _mock_image_client(mock_client_class)
        generate_image.invoke({"prompt": "test"})
        config = mock_client.models.generate_content.call_args.kwargs["config"]
        assert not config.tools

    @patch("src.agent.tools.image_generation.genai.Client")
    def test_use_search_enables_google_search_tool(self, mock_client_class: MagicMock) -> None:
        mock_client = _mock_image_client(mock_client_class)
        parsed = json.loads(generate_image.invoke({"prompt": "test", "use_search": True}))
        assert parsed["success"] is True
        config = mock_client.models.generate_content.call_args.kwargs["config"]
        assert len(config.tools) == 1
        assert config.tools[0].google_search is not None

    @patch("src.agent.tools.image_generation.genai.Client")
    def test_new_aspect_ratios_accepted(self, mock_client_class: MagicMock) -> None:
        mock_client = _mock_image_client(mock_client_class)
        for ratio in ("4:5", "5:4", "21:9"):
            parsed = json.loads(generate_image.invoke({"prompt": "test", "aspect_ratio": ratio}))
            assert parsed["success"] is True, ratio
            config = mock_client.models.generate_content.call_args.kwargs["config"]
            assert config.image_config.aspect_ratio == ratio
