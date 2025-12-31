"""Unit tests for file validation utilities."""

import base64
import io
from unittest.mock import patch

from PIL import Image

from src.utils.files import (
    MIME_TYPE_ALIASES,
    TEXT_BASED_MIME_TYPES,
    validate_files,
    verify_file_type_by_magic,
)

# =============================================================================
# Test Fixtures
# =============================================================================


def create_png_bytes(width: int = 10, height: int = 10) -> bytes:
    """Create a minimal PNG image as bytes."""
    img = Image.new("RGB", (width, height), color="red")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def create_jpeg_bytes(width: int = 10, height: int = 10) -> bytes:
    """Create a minimal JPEG image as bytes."""
    img = Image.new("RGB", (width, height), color="blue")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def create_gif_bytes(width: int = 10, height: int = 10) -> bytes:
    """Create a minimal GIF image as bytes."""
    img = Image.new("RGB", (width, height), color="green")
    buffer = io.BytesIO()
    img.save(buffer, format="GIF")
    return buffer.getvalue()


def create_webp_bytes(width: int = 10, height: int = 10) -> bytes:
    """Create a minimal WebP image as bytes."""
    img = Image.new("RGB", (width, height), color="yellow")
    buffer = io.BytesIO()
    img.save(buffer, format="WEBP")
    return buffer.getvalue()


# Minimal PDF bytes (PDF 1.0 header + minimal structure)
MINIMAL_PDF_BYTES = b"""%PDF-1.0
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj
xref
0 3
trailer<</Size 3/Root 1 0 R>>
startxref
0
%%EOF"""


# =============================================================================
# Tests for verify_file_type_by_magic
# =============================================================================


class TestVerifyFileTypeByMagic:
    """Tests for the verify_file_type_by_magic function."""

    def test_valid_png_image(self) -> None:
        """Should accept valid PNG with correct MIME type."""
        png_data = create_png_bytes()
        is_valid, error = verify_file_type_by_magic(png_data, "image/png", "test.png")
        assert is_valid is True
        assert error == ""

    def test_valid_jpeg_image(self) -> None:
        """Should accept valid JPEG with correct MIME type."""
        jpeg_data = create_jpeg_bytes()
        is_valid, error = verify_file_type_by_magic(jpeg_data, "image/jpeg", "test.jpg")
        assert is_valid is True
        assert error == ""

    def test_valid_gif_image(self) -> None:
        """Should accept valid GIF with correct MIME type."""
        gif_data = create_gif_bytes()
        is_valid, error = verify_file_type_by_magic(gif_data, "image/gif", "test.gif")
        assert is_valid is True
        assert error == ""

    def test_valid_webp_image(self) -> None:
        """Should accept valid WebP with correct MIME type."""
        webp_data = create_webp_bytes()
        is_valid, error = verify_file_type_by_magic(webp_data, "image/webp", "test.webp")
        assert is_valid is True
        assert error == ""

    def test_valid_pdf(self) -> None:
        """Should accept valid PDF with correct MIME type."""
        is_valid, error = verify_file_type_by_magic(
            MINIMAL_PDF_BYTES, "application/pdf", "test.pdf"
        )
        assert is_valid is True
        assert error == ""

    def test_spoofed_png_is_actually_jpeg(self) -> None:
        """Should reject JPEG file claiming to be PNG."""
        jpeg_data = create_jpeg_bytes()
        is_valid, error = verify_file_type_by_magic(jpeg_data, "image/png", "fake.png")
        assert is_valid is False
        assert "fake.png" in error
        assert "image/png" in error

    def test_spoofed_image_is_actually_pdf(self) -> None:
        """Should reject PDF file claiming to be image."""
        is_valid, error = verify_file_type_by_magic(MINIMAL_PDF_BYTES, "image/png", "fake.png")
        assert is_valid is False
        assert "fake.png" in error
        assert "image/png" in error

    def test_random_bytes_claiming_to_be_image(self) -> None:
        """Should reject random bytes claiming to be an image."""
        random_data = b"this is not an image at all, just random text"
        is_valid, error = verify_file_type_by_magic(random_data, "image/png", "fake.png")
        assert is_valid is False
        assert "fake.png" in error

    def test_text_based_types_skip_magic_validation(self) -> None:
        """Should skip magic validation for text-based MIME types."""
        # For text types, any content should be accepted since libmagic
        # detection is unreliable for text formats
        text_content = b"This is plain text content"

        for mime_type in TEXT_BASED_MIME_TYPES:
            is_valid, error = verify_file_type_by_magic(text_content, mime_type, "test.txt")
            assert is_valid is True, f"Failed for {mime_type}"
            assert error == ""

    def test_text_plain_skips_validation(self) -> None:
        """Should skip validation for text/plain even with binary content."""
        # Even if content looks binary, text/plain should be skipped
        binary_content = create_png_bytes()
        is_valid, error = verify_file_type_by_magic(binary_content, "text/plain", "misleading.txt")
        assert is_valid is True
        assert error == ""

    def test_json_skips_validation(self) -> None:
        """Should skip validation for application/json."""
        json_content = b'{"key": "value"}'
        is_valid, error = verify_file_type_by_magic(json_content, "application/json", "data.json")
        assert is_valid is True
        assert error == ""

    def test_csv_skips_validation(self) -> None:
        """Should skip validation for text/csv."""
        csv_content = b"name,age\nAlice,30\nBob,25"
        is_valid, error = verify_file_type_by_magic(csv_content, "text/csv", "data.csv")
        assert is_valid is True
        assert error == ""

    def test_markdown_skips_validation(self) -> None:
        """Should skip validation for text/markdown."""
        markdown_content = b"# Heading\n\nSome **bold** text"
        is_valid, error = verify_file_type_by_magic(markdown_content, "text/markdown", "readme.md")
        assert is_valid is True
        assert error == ""

    def test_magic_detection_error_fails_open(self) -> None:
        """Should accept file if magic detection throws an error."""
        # This ensures we don't block legitimate files due to magic library issues
        png_data = create_png_bytes()

        with patch("src.utils.files.magic.from_buffer") as mock_magic:
            mock_magic.side_effect = Exception("Magic library error")
            is_valid, error = verify_file_type_by_magic(png_data, "image/png", "test.png")
            assert is_valid is True
            assert error == ""

    def test_empty_file(self) -> None:
        """Should handle empty files appropriately."""
        # Empty files are typically detected as inode/x-empty or application/x-empty
        # For text-based types, should skip validation
        is_valid, error = verify_file_type_by_magic(b"", "text/plain", "empty.txt")
        assert is_valid is True

    def test_unmapped_mime_type_accepts_exact_match(self) -> None:
        """Should accept unmapped MIME type if detected matches claimed."""
        # Test with a hypothetical type not in MIME_TYPE_ALIASES
        with patch("src.utils.files.magic.from_buffer") as mock_magic:
            mock_magic.return_value = "application/octet-stream"
            # When claimed type matches detected type, should pass
            is_valid, error = verify_file_type_by_magic(
                b"some data", "application/octet-stream", "data.bin"
            )
            assert is_valid is True

    def test_unmapped_mime_type_rejects_mismatch(self) -> None:
        """Should reject unmapped MIME type if detected doesn't match claimed."""
        with patch("src.utils.files.magic.from_buffer") as mock_magic:
            mock_magic.return_value = "application/octet-stream"
            # When claimed type doesn't match detected type, should fail
            is_valid, error = verify_file_type_by_magic(
                b"some data", "application/x-custom", "data.custom"
            )
            assert is_valid is False
            assert "data.custom" in error


# =============================================================================
# Tests for validate_files (integration with magic validation)
# =============================================================================


class TestValidateFilesWithMagicBytes:
    """Tests for validate_files function including magic bytes validation."""

    def test_valid_png_file_passes(self) -> None:
        """Should accept valid PNG file."""
        png_data = create_png_bytes()
        files = [
            {
                "name": "test.png",
                "type": "image/png",
                "data": base64.b64encode(png_data).decode("utf-8"),
            }
        ]
        is_valid, error = validate_files(files)
        assert is_valid is True
        assert error == ""

    def test_valid_jpeg_file_passes(self) -> None:
        """Should accept valid JPEG file."""
        jpeg_data = create_jpeg_bytes()
        files = [
            {
                "name": "test.jpg",
                "type": "image/jpeg",
                "data": base64.b64encode(jpeg_data).decode("utf-8"),
            }
        ]
        is_valid, error = validate_files(files)
        assert is_valid is True
        assert error == ""

    def test_valid_pdf_file_passes(self) -> None:
        """Should accept valid PDF file."""
        files = [
            {
                "name": "test.pdf",
                "type": "application/pdf",
                "data": base64.b64encode(MINIMAL_PDF_BYTES).decode("utf-8"),
            }
        ]
        is_valid, error = validate_files(files)
        assert is_valid is True
        assert error == ""

    def test_spoofed_image_type_rejected(self) -> None:
        """Should reject file with mismatched content and claimed type."""
        # JPEG content claiming to be PNG
        jpeg_data = create_jpeg_bytes()
        files = [
            {
                "name": "fake.png",
                "type": "image/png",
                "data": base64.b64encode(jpeg_data).decode("utf-8"),
            }
        ]
        is_valid, error = validate_files(files)
        assert is_valid is False
        assert "fake.png" in error
        assert "image/png" in error

    def test_pdf_claiming_to_be_image_rejected(self) -> None:
        """Should reject PDF claiming to be an image."""
        files = [
            {
                "name": "document.png",
                "type": "image/png",
                "data": base64.b64encode(MINIMAL_PDF_BYTES).decode("utf-8"),
            }
        ]
        is_valid, error = validate_files(files)
        assert is_valid is False
        assert "document.png" in error

    def test_text_file_passes_without_magic_check(self) -> None:
        """Should accept text files without strict magic checking."""
        text_content = b"Hello, this is a text file.\nWith multiple lines."
        files = [
            {
                "name": "readme.txt",
                "type": "text/plain",
                "data": base64.b64encode(text_content).decode("utf-8"),
            }
        ]
        is_valid, error = validate_files(files)
        assert is_valid is True
        assert error == ""

    def test_json_file_passes(self) -> None:
        """Should accept JSON files."""
        json_content = b'{"name": "test", "values": [1, 2, 3]}'
        files = [
            {
                "name": "config.json",
                "type": "application/json",
                "data": base64.b64encode(json_content).decode("utf-8"),
            }
        ]
        is_valid, error = validate_files(files)
        assert is_valid is True
        assert error == ""

    def test_multiple_valid_files_pass(self) -> None:
        """Should accept multiple valid files."""
        png_data = create_png_bytes()
        jpeg_data = create_jpeg_bytes()
        files = [
            {
                "name": "image1.png",
                "type": "image/png",
                "data": base64.b64encode(png_data).decode("utf-8"),
            },
            {
                "name": "image2.jpg",
                "type": "image/jpeg",
                "data": base64.b64encode(jpeg_data).decode("utf-8"),
            },
        ]
        is_valid, error = validate_files(files)
        assert is_valid is True
        assert error == ""

    def test_one_spoofed_file_in_batch_rejected(self) -> None:
        """Should reject batch if any file fails magic validation."""
        png_data = create_png_bytes()
        jpeg_data = create_jpeg_bytes()
        files = [
            {
                "name": "valid.png",
                "type": "image/png",
                "data": base64.b64encode(png_data).decode("utf-8"),
            },
            {
                "name": "spoofed.png",
                "type": "image/png",
                "data": base64.b64encode(jpeg_data).decode("utf-8"),  # JPEG claiming PNG
            },
        ]
        is_valid, error = validate_files(files)
        assert is_valid is False
        assert "spoofed.png" in error

    def test_magic_validation_happens_after_size_check(self) -> None:
        """Magic validation should only run after size check passes."""
        # Create oversized data
        large_data = b"x" * (21 * 1024 * 1024)  # 21 MB
        files = [
            {
                "name": "large.png",
                "type": "image/png",
                "data": base64.b64encode(large_data).decode("utf-8"),
            }
        ]

        with patch("src.utils.files.verify_file_type_by_magic") as mock_verify:
            is_valid, error = validate_files(files)
            # Should fail on size before reaching magic validation
            assert is_valid is False
            assert "exceeds" in error
            # Magic verification should not have been called
            mock_verify.assert_not_called()


# =============================================================================
# Tests for MIME_TYPE_ALIASES configuration
# =============================================================================


class TestMimeTypeAliases:
    """Tests for MIME type alias configuration."""

    def test_all_image_types_have_mappings(self) -> None:
        """Should have mappings for all common image types."""
        expected_image_types = {"image/png", "image/jpeg", "image/gif", "image/webp"}
        for mime_type in expected_image_types:
            assert mime_type in MIME_TYPE_ALIASES, f"Missing mapping for {mime_type}"

    def test_pdf_has_mapping(self) -> None:
        """Should have mapping for PDF."""
        assert "application/pdf" in MIME_TYPE_ALIASES

    def test_text_types_have_flexible_mappings(self) -> None:
        """Text types should have flexible mappings for libmagic detection quirks."""
        text_types = {"text/plain", "text/markdown", "text/csv", "application/json"}
        for mime_type in text_types:
            assert mime_type in MIME_TYPE_ALIASES, f"Missing mapping for {mime_type}"
            # Text types should accept text/plain at minimum
            assert (
                "text/plain" in MIME_TYPE_ALIASES[mime_type] or mime_type in TEXT_BASED_MIME_TYPES
            )

    def test_text_based_types_match_skip_list(self) -> None:
        """TEXT_BASED_MIME_TYPES should be skipped for magic validation."""
        # These types are unreliably detected by libmagic, so we skip them
        expected_skip_types = {"text/plain", "text/markdown", "text/csv", "application/json"}
        assert TEXT_BASED_MIME_TYPES == expected_skip_types
