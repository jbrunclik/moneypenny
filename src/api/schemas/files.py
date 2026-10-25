"""File attachment, file metadata, source and thumbnail schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from src.api.schemas.base import RequestModel, ResponseModel
from src.config import Config


class FileAttachment(RequestModel):
    """Schema for file attachments in chat requests.

    Validates structure only. Content validation (base64 decoding, size checking)
    is handled by validate_files() in src/utils/files.py.
    """

    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., min_length=1)  # MIME type
    data: str = Field(..., min_length=1)  # Base64-encoded data

    @field_validator("type")
    @classmethod
    def validate_mime_type(cls, v: str) -> str:
        """Validate MIME type is in allowed list."""
        if v not in Config.ALLOWED_FILE_TYPES:
            allowed = ", ".join(sorted(Config.ALLOWED_FILE_TYPES))
            raise ValueError(f"File type '{v}' not allowed. Allowed: {allowed}")
        return v


class FileMetadataResponse(ResponseModel):
    """File metadata in message responses (excludes full data for performance)."""

    name: str
    type: str
    messageId: str | None = None  # noqa: N815 - camelCase is the API wire format
    fileIndex: int | None = None  # noqa: N815 - camelCase is the API wire format


class SourceResponse(ResponseModel):
    """Web search source citation."""

    title: str
    url: str


class GeneratedImageResponse(ResponseModel):
    """Generated image metadata."""

    prompt: str
    image_index: int | None = None


class ThumbnailPendingResponse(ResponseModel):
    """Response when thumbnail is still being generated (202)."""

    status: Literal["pending"] = "pending"
