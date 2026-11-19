"""File attachments: their shapes and validation."""

import base64
import binascii
from typing import NotRequired, TypedDict

import magic

from src.config import Config
from src.utils.logging import get_logger
from src.utils.office_text import DOCX, PPTX, XLSX

logger = get_logger(__name__)


class UploadedFile(TypedDict):
    """A file as a turn carries it: the bytes base64-encoded (the chat request's
    FileAttachment, or a tool's output), plus what the turn adds on the way."""

    name: str
    type: str  # MIME type
    data: str
    thumbnail: NotRequired[str | None]  # base64 JPEG (images)
    thumbnail_status: NotRequired[str]  # ThumbnailStatus value
    gemini_file_uri: NotRequired[str]  # set when uploaded to the Files API
    gemini_upload_error: NotRequired[str]
    # message_id:file_index once the message is saved - what execute_code(files=...) takes
    history_file_id: NotRequired[str]


class StoredFile(TypedDict):
    """A file attachment as `messages.files` keeps it; its bytes and thumbnail
    are in the blob store (src/db/blob_store.py)."""

    name: str
    type: str  # MIME type
    size: NotRequired[int]  # bytes
    has_thumbnail: NotRequired[bool]
    thumbnail_status: NotRequired[str]  # ThumbnailStatus value
    gemini_file_uri: NotRequired[str]
    gemini_upload_error: NotRequired[str]
    # Rows from before the blob store kept the bytes inline (base64)
    data: NotRequired[str]
    thumbnail: NotRequired[str]


# No octet-stream for either: every libmagic in use names these formats, and
# an unknown-bytes allowance would let anything through as a memo or document
_OFFICE_MAGIC = {"application/zip"}
# Compound File (OLE) header: encrypted OOXML and pre-2007 .doc/.xls/.ppt
_OLE_SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
_M4A_MAGIC = {"audio/x-m4a", "audio/mp4", "video/mp4"}
_WAV_MAGIC = {"audio/x-wav", "audio/wav", "audio/vnd.wave"}

# Mapping of allowed MIME types to their expected magic-detected MIME types
# Some MIME types may be detected differently by libmagic than what browsers send
MIME_TYPE_ALIASES: dict[str, set[str]] = {
    # Images - straightforward mapping
    "image/png": {"image/png"},
    "image/jpeg": {"image/jpeg"},
    "image/gif": {"image/gif"},
    "image/webp": {"image/webp", "application/octet-stream"},
    # HEIC/HEIF (iPhone photos) - browsers declare image/heic or image/heif
    # interchangeably; libmagic reports the heif family (and -sequence for
    # bursts/live photos), so both claimed types accept the whole family
    # (octet-stream: older libmagic builds don't know the HEIF container,
    # same precedent as webp above)
    "image/heic": {
        "image/heic",
        "image/heif",
        "image/heic-sequence",
        "image/heif-sequence",
        "application/octet-stream",
    },
    "image/heif": {
        "image/heic",
        "image/heif",
        "image/heic-sequence",
        "image/heif-sequence",
        "application/octet-stream",
    },
    # PDF
    "application/pdf": {"application/pdf"},
    # Videos - libmagic detects container formats; .mov sometimes reads as mp4 family
    "video/mp4": {"video/mp4", "video/x-m4v"},
    "video/quicktime": {"video/quicktime", "video/mp4"},
    "video/webm": {"video/webm", "video/x-matroska"},
    # Audio (Nov 16 2026). m4a is AAC in an MP4 container: older libmagic
    # builds read it as mp4 video
    "audio/mpeg": {"audio/mpeg", "audio/mp3"},
    "audio/mp4": _M4A_MAGIC,
    "audio/x-m4a": _M4A_MAGIC,
    "audio/wav": _WAV_MAGIC,
    "audio/x-wav": _WAV_MAGIC,
    "audio/ogg": {"audio/ogg", "application/ogg", "audio/x-vorbis+ogg"},
    "audio/flac": {"audio/flac", "audio/x-flac"},
    "audio/aac": {"audio/aac", "audio/x-aac", "audio/x-hx-aac-adts"},
    # Chrome's recordings: libmagic names the container, not the content
    "audio/webm": {"audio/webm", "video/webm", "video/x-matroska"},
    # Office (Nov 16 2026): zip containers; libmagic names the type when it
    # finds the part it knows, else a plain zip
    DOCX: _OFFICE_MAGIC | {DOCX},
    XLSX: _OFFICE_MAGIC | {XLSX},
    PPTX: _OFFICE_MAGIC | {PPTX},
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
    except Exception as e:  # fail open: detection must not block an upload
        logger.warning(
            "Failed to detect file type by magic bytes",
            extra={"file_name": file_name, "error": str(e)},
            exc_info=True,
        )
        # Fail open for detection errors - the file already passed MIME whitelist check
        return True, ""

    # A password-protected (or pre-2007) Office file is an OLE container, not
    # a zip: say what to do instead of "does not match"
    if claimed_mime_type in (DOCX, XLSX, PPTX) and file_data.startswith(_OLE_SIGNATURE):
        return (
            False,
            f"File '{file_name}' is password-protected or in the old Office format - "
            "save it without a password as .docx, .xlsx or .pptx",
        )

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

    # Some libmagic builds detect video containers only via from_file, not
    # from_buffer (returning application/octet-stream). Fall back to checking
    # the container signature directly so spoof detection stays meaningful.
    if detected_mime_type == "application/octet-stream" and _matches_video_signature(
        file_data, claimed_mime_type
    ):
        # INFO (not DEBUG): this softer validation path should stay observable
        # in production logs in case abuse patterns emerge
        logger.info(
            "Magic validation passed via container signature",
            extra={"file_name": file_name, "claimed_type": claimed_mime_type},
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


def _matches_video_signature(file_data: bytes, claimed_mime_type: str) -> bool:
    """Check a video container's magic bytes directly.

    MP4/QuickTime are ISO-BMFF ("ftyp" box at offset 4); WebM is
    Matroska/EBML (magic bytes at offset 0).
    """
    if claimed_mime_type in ("video/mp4", "video/quicktime"):
        return len(file_data) >= 8 and file_data[4:8] == b"ftyp"
    if claimed_mime_type == "video/webm":
        return file_data.startswith(b"\x1a\x45\xdf\xa3")
    return False


# Browsers' names for audio types Gemini knows by another (m4a is AAC in MP4)
_GEMINI_MIME_NAMES = {"audio/x-m4a": "audio/mp4", "audio/x-wav": "audio/wav"}


def is_media_mime(mime_type: str) -> bool:
    """Video or audio: sent to the model through the Gemini Files API."""
    return mime_type.startswith(("video/", "audio/"))


def gemini_mime_type(mime_type: str) -> str:
    """The MIME type to tell Gemini for an attachment."""
    return _GEMINI_MIME_NAMES.get(mime_type, mime_type)


# libmagic reads at most this much of a buffer (its default bytes_max), so
# checking a prefix this long sees exactly what checking the whole file does
MAGIC_PREFIX_BYTES = 1024 * 1024


def decoded_size(data: str) -> int:
    """The byte size of base64 `data`, without decoding it."""
    return len(data) * 3 // 4 - (2 if data.endswith("==") else 1 if data.endswith("=") else 0)


def _decoded_prefix(data: str, size: int) -> bytes:
    """The first `size` bytes of base64 `data`, decoding only those."""
    chars = (size + 2) // 3 * 4
    return base64.b64decode(data[:chars])


def max_size_for_mime(mime_type: str) -> int:
    """Per-type upload size limit (videos get a larger allowance)."""
    if mime_type.startswith("video/"):
        return Config.MAX_VIDEO_FILE_SIZE_BYTES
    return Config.MAX_FILE_SIZE_BYTES


def validate_files(files: list[UploadedFile]) -> tuple[bool, str]:
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

        # Size from the base64 length and the type from the first bytes: a
        # 100 MB video was decoded whole here and three more times later on
        data = file.get("data", "")
        size = decoded_size(data)
        max_size = max_size_for_mime(file_type)
        if size > max_size:
            max_mb = max_size / (1024 * 1024)
            logger.warning(
                "File too large",
                extra={"file_name": file_name, "size": size, "max_size": max_size},
            )
            return False, f"File '{file_name}' exceeds {max_mb:.0f}MB limit"
        try:
            if len(data) % 4:
                raise binascii.Error("Incorrect padding")
            decoded_data = _decoded_prefix(data, MAGIC_PREFIX_BYTES)
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
