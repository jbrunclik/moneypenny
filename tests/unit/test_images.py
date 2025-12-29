"""Unit tests for src/utils/images.py."""

import base64
import io
import json

from PIL import Image

from src.config import Config
from src.utils.images import (
    extract_code_output_files_from_tool_results,
    extract_generated_images_from_tool_results,
    generate_thumbnail,
    process_image_files,
)


class TestGenerateThumbnail:
    """Tests for generate_thumbnail function."""

    def test_generates_valid_thumbnail(self, sample_png_base64: str) -> None:
        """Should generate a valid thumbnail from PNG image."""
        thumbnail = generate_thumbnail(sample_png_base64, "image/png")

        assert thumbnail is not None
        # Verify it's valid base64 that decodes to an image
        decoded = base64.b64decode(thumbnail)
        img = Image.open(io.BytesIO(decoded))
        assert img.size[0] <= Config.THUMBNAIL_MAX_SIZE[0]
        assert img.size[1] <= Config.THUMBNAIL_MAX_SIZE[1]

    def test_scales_down_large_image(self, large_png_base64: str) -> None:
        """Large images should be scaled down to fit max size."""
        thumbnail = generate_thumbnail(large_png_base64, "image/png")

        assert thumbnail is not None
        decoded = base64.b64decode(thumbnail)
        img = Image.open(io.BytesIO(decoded))

        # Original was 1000x1000, should be scaled to max 400x400
        assert img.size[0] <= Config.THUMBNAIL_MAX_SIZE[0]
        assert img.size[1] <= Config.THUMBNAIL_MAX_SIZE[1]

    def test_small_image_not_upscaled(self, sample_png_base64: str) -> None:
        """Small images should not be upscaled."""
        # sample_png_base64 is 100x100
        thumbnail = generate_thumbnail(sample_png_base64, "image/png")

        assert thumbnail is not None
        decoded = base64.b64decode(thumbnail)
        img = Image.open(io.BytesIO(decoded))

        # Should remain 100x100, not upscaled to 400x400
        assert img.size[0] <= 100
        assert img.size[1] <= 100

    def test_returns_none_for_non_image_mime_type(self) -> None:
        """Non-image MIME types should return None."""
        result = generate_thumbnail("some_data", "application/pdf")
        assert result is None

        result = generate_thumbnail("some_data", "text/plain")
        assert result is None

    def test_handles_invalid_base64(self) -> None:
        """Invalid base64 should return None (not crash)."""
        result = generate_thumbnail("not_valid_base64!!!", "image/png")
        assert result is None

    def test_handles_empty_data(self) -> None:
        """Empty data should return None."""
        result = generate_thumbnail("", "image/png")
        assert result is None

    def test_jpeg_output_quality(self) -> None:
        """JPEG thumbnails should be generated correctly."""
        from tests.fixtures.images import create_test_jpeg

        jpeg_data = create_test_jpeg(200, 200)
        thumbnail = generate_thumbnail(jpeg_data, "image/jpeg")

        assert thumbnail is not None
        decoded = base64.b64decode(thumbnail)
        img = Image.open(io.BytesIO(decoded))
        assert img.format in ("JPEG", "MPO")


class TestProcessImageFiles:
    """Tests for process_image_files function."""

    def test_adds_thumbnail_to_images(self, sample_png_base64: str) -> None:
        """Should add thumbnail key to image files."""
        files = [{"name": "test.png", "type": "image/png", "data": sample_png_base64}]

        result = process_image_files(files)

        assert len(result) == 1
        assert "thumbnail" in result[0]
        assert result[0]["thumbnail"] is not None

    def test_skips_non_image_files(self) -> None:
        """Non-image files should not get thumbnails."""
        files = [{"name": "doc.pdf", "type": "application/pdf", "data": "base64data"}]

        result = process_image_files(files)

        assert len(result) == 1
        assert "thumbnail" not in result[0]

    def test_processes_mixed_files(self, sample_png_base64: str) -> None:
        """Should process mixed file types correctly."""
        files = [
            {"name": "image.png", "type": "image/png", "data": sample_png_base64},
            {"name": "doc.txt", "type": "text/plain", "data": "text content"},
            {"name": "photo.jpg", "type": "image/jpeg", "data": sample_png_base64},
        ]

        result = process_image_files(files)

        assert len(result) == 3
        assert "thumbnail" in result[0]  # PNG
        assert "thumbnail" not in result[1]  # TXT
        assert "thumbnail" in result[2]  # JPEG

    def test_handles_empty_list(self) -> None:
        """Empty file list should return empty list."""
        result = process_image_files([])
        assert result == []

    def test_preserves_original_data(self, sample_png_base64: str) -> None:
        """Original file data should be preserved."""
        files = [{"name": "test.png", "type": "image/png", "data": sample_png_base64}]

        result = process_image_files(files)

        assert result[0]["data"] == sample_png_base64
        assert result[0]["name"] == "test.png"
        assert result[0]["type"] == "image/png"


class TestExtractGeneratedImagesFromToolResults:
    """Tests for extract_generated_images_from_tool_results function."""

    def test_extracts_image_from_tool_result(self) -> None:
        """Should extract image from generate_image tool result."""
        tool_results = [
            {
                "type": "tool",
                "content": json.dumps(
                    {
                        "success": True,
                        "_full_result": {
                            "image": {"data": "base64imagedata", "mime_type": "image/png"}
                        },
                    }
                ),
            }
        ]

        files = extract_generated_images_from_tool_results(tool_results)

        assert len(files) == 1
        assert files[0]["type"] == "image/png"
        assert files[0]["data"] == "base64imagedata"
        assert "generated_image" in files[0]["name"]

    def test_handles_empty_results(self) -> None:
        """Empty results should return empty list."""
        files = extract_generated_images_from_tool_results([])
        assert files == []

    def test_skips_non_image_tool_results(self) -> None:
        """Non-image tool results should be skipped."""
        tool_results = [{"type": "tool", "content": json.dumps({"query": "test", "results": []})}]

        files = extract_generated_images_from_tool_results(tool_results)
        assert files == []

    def test_skips_non_tool_messages(self) -> None:
        """Non-tool messages should be skipped."""
        tool_results = [
            {"type": "ai", "content": "Hello"},
            {"type": "human", "content": "Hi"},
        ]

        files = extract_generated_images_from_tool_results(tool_results)
        assert files == []

    def test_skips_malformed_json(self) -> None:
        """Malformed JSON content should be skipped."""
        tool_results = [{"type": "tool", "content": "not valid json"}]

        files = extract_generated_images_from_tool_results(tool_results)
        assert files == []

    def test_skips_missing_full_result(self) -> None:
        """Results without _full_result should be skipped."""
        tool_results = [
            {
                "type": "tool",
                "content": json.dumps({"success": True, "message": "Done"}),
            }
        ]

        files = extract_generated_images_from_tool_results(tool_results)
        assert files == []

    def test_skips_missing_image_data(self) -> None:
        """Results without image data should be skipped."""
        tool_results = [
            {
                "type": "tool",
                "content": json.dumps({"success": True, "_full_result": {"other": "data"}}),
            }
        ]

        files = extract_generated_images_from_tool_results(tool_results)
        assert files == []

    def test_extracts_multiple_images(self) -> None:
        """Should extract multiple images from multiple tool results."""
        tool_results = [
            {
                "type": "tool",
                "content": json.dumps(
                    {
                        "success": True,
                        "_full_result": {"image": {"data": "image1data", "mime_type": "image/png"}},
                    }
                ),
            },
            {
                "type": "tool",
                "content": json.dumps(
                    {
                        "success": True,
                        "_full_result": {
                            "image": {"data": "image2data", "mime_type": "image/jpeg"}
                        },
                    }
                ),
            },
        ]

        files = extract_generated_images_from_tool_results(tool_results)

        assert len(files) == 2
        assert files[0]["data"] == "image1data"
        assert files[1]["data"] == "image2data"

    def test_default_mime_type(self) -> None:
        """Should use PNG as default MIME type."""
        tool_results = [
            {
                "type": "tool",
                "content": json.dumps(
                    {
                        "success": True,
                        "_full_result": {
                            "image": {
                                "data": "imagedata",
                                # No mime_type specified
                            }
                        },
                    }
                ),
            }
        ]

        files = extract_generated_images_from_tool_results(tool_results)

        assert len(files) == 1
        assert files[0]["type"] == "image/png"

    def test_generates_thumbnails(self, sample_png_base64: str) -> None:
        """Should generate thumbnails for extracted images."""
        tool_results = [
            {
                "type": "tool",
                "content": json.dumps(
                    {
                        "success": True,
                        "_full_result": {
                            "image": {"data": sample_png_base64, "mime_type": "image/png"}
                        },
                    }
                ),
            }
        ]

        files = extract_generated_images_from_tool_results(tool_results)

        assert len(files) == 1
        assert "thumbnail" in files[0]


class TestExtractCodeOutputFilesFromToolResults:
    """Tests for extract_code_output_files_from_tool_results function."""

    def test_extracts_pdf_from_tool_result(self) -> None:
        """Should extract PDF file from execute_code tool result."""
        tool_results = [
            {
                "type": "tool",
                "content": json.dumps(
                    {
                        "success": True,
                        "stdout": "PDF generated",
                        "_full_result": {
                            "files": [
                                {
                                    "name": "report.pdf",
                                    "mime_type": "application/pdf",
                                    "data": "base64pdfdata",
                                    "size": 1234,
                                }
                            ]
                        },
                    }
                ),
            }
        ]

        files = extract_code_output_files_from_tool_results(tool_results)

        assert len(files) == 1
        assert files[0]["name"] == "report.pdf"
        assert files[0]["type"] == "application/pdf"
        assert files[0]["data"] == "base64pdfdata"

    def test_extracts_image_with_thumbnail(self, sample_png_base64: str) -> None:
        """Should extract image file and generate thumbnail."""
        tool_results = [
            {
                "type": "tool",
                "content": json.dumps(
                    {
                        "success": True,
                        "_full_result": {
                            "files": [
                                {
                                    "name": "plot.png",
                                    "mime_type": "image/png",
                                    "data": sample_png_base64,
                                    "size": 5000,
                                }
                            ]
                        },
                    }
                ),
            }
        ]

        files = extract_code_output_files_from_tool_results(tool_results)

        assert len(files) == 1
        assert files[0]["name"] == "plot.png"
        assert files[0]["type"] == "image/png"
        assert "thumbnail" in files[0]

    def test_extracts_multiple_files(self) -> None:
        """Should extract multiple files from single tool result."""
        tool_results = [
            {
                "type": "tool",
                "content": json.dumps(
                    {
                        "success": True,
                        "_full_result": {
                            "files": [
                                {
                                    "name": "data.csv",
                                    "mime_type": "text/csv",
                                    "data": "csvdata",
                                    "size": 100,
                                },
                                {
                                    "name": "chart.png",
                                    "mime_type": "image/png",
                                    "data": "pngdata",
                                    "size": 2000,
                                },
                            ]
                        },
                    }
                ),
            }
        ]

        files = extract_code_output_files_from_tool_results(tool_results)

        assert len(files) == 2
        assert files[0]["name"] == "data.csv"
        assert files[1]["name"] == "chart.png"

    def test_handles_empty_results(self) -> None:
        """Empty results should return empty list."""
        files = extract_code_output_files_from_tool_results([])
        assert files == []

    def test_skips_non_tool_messages(self) -> None:
        """Non-tool messages should be skipped."""
        tool_results = [
            {"type": "ai", "content": "Hello"},
            {"type": "human", "content": "Hi"},
        ]

        files = extract_code_output_files_from_tool_results(tool_results)
        assert files == []

    def test_skips_malformed_json(self) -> None:
        """Malformed JSON content should be skipped."""
        tool_results = [{"type": "tool", "content": "not valid json"}]

        files = extract_code_output_files_from_tool_results(tool_results)
        assert files == []

    def test_skips_missing_full_result(self) -> None:
        """Results without _full_result should be skipped."""
        tool_results = [
            {
                "type": "tool",
                "content": json.dumps({"success": True, "stdout": "Hello"}),
            }
        ]

        files = extract_code_output_files_from_tool_results(tool_results)
        assert files == []

    def test_skips_missing_files(self) -> None:
        """Results without files should be skipped."""
        tool_results = [
            {
                "type": "tool",
                "content": json.dumps({"success": True, "_full_result": {"other": "data"}}),
            }
        ]

        files = extract_code_output_files_from_tool_results(tool_results)
        assert files == []

    def test_skips_files_without_name(self) -> None:
        """Files without name should be skipped."""
        tool_results = [
            {
                "type": "tool",
                "content": json.dumps(
                    {
                        "success": True,
                        "_full_result": {"files": [{"mime_type": "text/plain", "data": "data"}]},
                    }
                ),
            }
        ]

        files = extract_code_output_files_from_tool_results(tool_results)
        assert files == []

    def test_skips_files_without_data(self) -> None:
        """Files without data should be skipped."""
        tool_results = [
            {
                "type": "tool",
                "content": json.dumps(
                    {
                        "success": True,
                        "_full_result": {
                            "files": [{"name": "file.txt", "mime_type": "text/plain"}]
                        },
                    }
                ),
            }
        ]

        files = extract_code_output_files_from_tool_results(tool_results)
        assert files == []

    def test_default_mime_type(self) -> None:
        """Should use octet-stream as default MIME type."""
        tool_results = [
            {
                "type": "tool",
                "content": json.dumps(
                    {
                        "success": True,
                        "_full_result": {
                            "files": [
                                {
                                    "name": "unknown.xyz",
                                    "data": "somedata",
                                    # No mime_type specified
                                }
                            ]
                        },
                    }
                ),
            }
        ]

        files = extract_code_output_files_from_tool_results(tool_results)

        assert len(files) == 1
        assert files[0]["type"] == "application/octet-stream"

    def test_extracts_from_multiple_tool_results(self) -> None:
        """Should extract files from multiple tool results."""
        tool_results = [
            {
                "type": "tool",
                "content": json.dumps(
                    {
                        "success": True,
                        "_full_result": {
                            "files": [
                                {"name": "file1.txt", "mime_type": "text/plain", "data": "data1"}
                            ]
                        },
                    }
                ),
            },
            {
                "type": "tool",
                "content": json.dumps(
                    {
                        "success": True,
                        "_full_result": {
                            "files": [
                                {
                                    "name": "file2.pdf",
                                    "mime_type": "application/pdf",
                                    "data": "data2",
                                }
                            ]
                        },
                    }
                ),
            },
        ]

        files = extract_code_output_files_from_tool_results(tool_results)

        assert len(files) == 2
        assert files[0]["name"] == "file1.txt"
        assert files[1]["name"] == "file2.pdf"
