"""File validation utilities."""

import base64
import binascii
from typing import Any

import magic

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Mapping of allowed MIME types to their expected magic-detected MIME types
# Some MIME types may be detected differently by libmagic than what browsers send
MIME_TYPE_ALIASES: dict[str, set[str]] = {
    # Images - straightforward mapping
    "image/png": {"image/png"},
    "image/jpeg": {"image/jpeg"},
    "image/gif": {"image/gif"},
    "image/webp": {"image/webp"},
    # PDF
    "application/pdf": {"application/pdf"},
    # Text files - libmagic may detect various text subtypes
    "text/plain": {
        "text/plain",
        "text/x-c",  # C source code
        "text/x-c++",  # C++ source code
        "text/x-python",  # Python source code
        "text/x-java",  # Java source code
        "text/x-script.python",  # Another Python variant
        "application/x-empty",  # Empty files
        "inode/x-empty",  # Empty files (some systems)
    },
    "text/markdown": {
        "text/plain",  # Markdown is detected as plain text
        "text/x-c",  # Markdown with code blocks
        "text/html",  # Markdown with HTML
        "application/x-empty",
        "inode/x-empty",
    },
    "text/csv": {
        "text/plain",  # CSV is detected as plain text
        "text/csv",
        "application/csv",
        "application/x-empty",
        "inode/x-empty",
    },
    # JSON - libmagic usually detects as text/plain or application/json
    "application/json": {
        "text/plain",
        "application/json",
        "application/x-empty",
        "inode/x-empty",
    },
}

# MIME types that don't need magic validation (text-based formats where
# the client-provided MIME type is authoritative based on file extension)
TEXT_BASED_MIME_TYPES: set[str] = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
}


def verify_file_type_by_magic(
    file_data: bytes, claimed_mime_type: str, file_name: str
) -> tuple[bool, str]:
    """Verify that file content matches the claimed MIME type using magic bytes.

    Args:
        file_data: Decoded binary file data
        claimed_mime_type: MIME type claimed by the client
        file_name: Name of the file (for error messages)

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Skip validation for text-based formats - they're detected inconsistently
    # by libmagic and the client's file extension is authoritative
    if claimed_mime_type in TEXT_BASED_MIME_TYPES:
        logger.debug(
            "Skipping magic validation for text-based file",
            extra={"file_name": file_name, "claimed_type": claimed_mime_type},
        )
        return True, ""

    # Detect actual MIME type from file content
    try:
        detected_mime_type = magic.from_buffer(file_data, mime=True)
    except Exception as e:
        logger.warning(
            "Failed to detect file type by magic bytes",
            extra={"file_name": file_name, "error": str(e)},
        )
        # Fail open for detection errors - the file already passed MIME whitelist check
        return True, ""

    # Get allowed magic types for the claimed MIME type
    allowed_magic_types = MIME_TYPE_ALIASES.get(claimed_mime_type)

    if allowed_magic_types is None:
        # No alias mapping defined - accept if detected type matches claimed type
        if detected_mime_type == claimed_mime_type:
            return True, ""
        logger.warning(
            "File content does not match claimed type",
            extra={
                "file_name": file_name,
                "claimed_type": claimed_mime_type,
                "detected_type": detected_mime_type,
            },
        )
        return (
            False,
            f"File '{file_name}' content does not match claimed type '{claimed_mime_type}'",
        )

    # Check if detected type is in the allowed set
    if detected_mime_type in allowed_magic_types:
        logger.debug(
            "Magic validation passed",
            extra={
                "file_name": file_name,
                "claimed_type": claimed_mime_type,
                "detected_type": detected_mime_type,
            },
        )
        return True, ""

    # Type mismatch - potential spoofing attempt
    logger.warning(
        "File content does not match claimed type",
        extra={
            "file_name": file_name,
            "claimed_type": claimed_mime_type,
            "detected_type": detected_mime_type,
            "allowed_types": list(allowed_magic_types),
        },
    )
    return (
        False,
        f"File '{file_name}' content does not match claimed type '{claimed_mime_type}'",
    )


def validate_files(files: list[dict[str, Any]]) -> tuple[bool, str]:
    """Validate uploaded files against config limits.

    Args:
        files: List of file dictionaries with 'name', 'type', 'data' keys

    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(files) > Config.MAX_FILES_PER_MESSAGE:
        logger.warning(
            "Too many files",
            extra={"file_count": len(files), "max_allowed": Config.MAX_FILES_PER_MESSAGE},
        )
        return False, f"Too many files. Maximum is {Config.MAX_FILES_PER_MESSAGE}"

    for file in files:
        file_name = file.get("name", "unknown")
        # Check file type
        file_type = file.get("type", "")
        if file_type not in Config.ALLOWED_FILE_TYPES:
            logger.warning(
                "File type not allowed", extra={"file_name": file_name, "file_type": file_type}
            )
            return False, f"File type '{file_type}' is not allowed"

        # Decode and check file size (base64 is ~4/3 larger than binary)
        data = file.get("data", "")
        try:
            decoded_data = base64.b64decode(data)
            if len(decoded_data) > Config.MAX_FILE_SIZE:
                max_mb = Config.MAX_FILE_SIZE / (1024 * 1024)
                logger.warning(
                    "File too large",
                    extra={
                        "file_name": file_name,
                        "size": len(decoded_data),
                        "max_size": Config.MAX_FILE_SIZE,
                    },
                )
                return False, f"File '{file_name}' exceeds {max_mb:.0f}MB limit"
        except binascii.Error as e:
            logger.warning(
                "Invalid file data encoding", extra={"file_name": file_name, "error": str(e)}
            )
            return False, "Invalid file data encoding"

        # Verify file content matches claimed MIME type using magic bytes
        is_valid, error_msg = verify_file_type_by_magic(decoded_data, file_type, file_name)
        if not is_valid:
            return False, error_msg

    logger.debug("File validation passed", extra={"file_count": len(files)})
    return True, ""
