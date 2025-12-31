"""Pydantic schemas for API request validation.

This module defines Pydantic models for all API request payloads. These schemas
provide automatic validation of request structure, types, and constraints.

For file content validation (base64 decoding, size limits), see validate_files()
in src/utils/files.py which handles the content-level validation after Pydantic
validates the structure.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from src.config import Config

# -----------------------------------------------------------------------------
# File Schema (reusable)
# -----------------------------------------------------------------------------


class FileAttachment(BaseModel):
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


# -----------------------------------------------------------------------------
# Auth Schemas
# -----------------------------------------------------------------------------


class GoogleAuthRequest(BaseModel):
    """Schema for POST /auth/google."""

    credential: str = Field(..., min_length=1)


# -----------------------------------------------------------------------------
# Conversation Schemas
# -----------------------------------------------------------------------------


class CreateConversationRequest(BaseModel):
    """Schema for POST /api/conversations."""

    model: str | None = None  # Defaults to Config.DEFAULT_MODEL in route

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str | None) -> str | None:
        """Validate model is in available models list."""
        if v is not None and v not in Config.MODELS:
            models = list(Config.MODELS.keys())
            raise ValueError(f"Invalid model. Choose from: {models}")
        return v


class UpdateConversationRequest(BaseModel):
    """Schema for PATCH /api/conversations/<conv_id>."""

    title: str | None = Field(None, min_length=1, max_length=200)
    model: str | None = None

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str | None) -> str | None:
        """Validate model is in available models list."""
        if v is not None and v not in Config.MODELS:
            models = list(Config.MODELS.keys())
            raise ValueError(f"Invalid model. Choose from: {models}")
        return v


# -----------------------------------------------------------------------------
# Chat Schemas
# -----------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """Schema for POST /api/conversations/<conv_id>/chat/batch and /chat/stream.

    Validates structure. File content validation happens separately via
    validate_files() in src/utils/files.py.
    """

    message: str = Field(default="")
    files: list[FileAttachment] = Field(default_factory=list)
    force_tools: list[str] = Field(default_factory=list)

    @field_validator("files")
    @classmethod
    def validate_files_count(cls, v: list[FileAttachment]) -> list[FileAttachment]:
        """Validate file count limit."""
        if len(v) > Config.MAX_FILES_PER_MESSAGE:
            raise ValueError(f"Too many files. Maximum is {Config.MAX_FILES_PER_MESSAGE}")
        return v

    @model_validator(mode="after")
    def validate_message_or_files(self) -> ChatRequest:
        """Ensure at least message or files is provided."""
        message_text = self.message.strip() if self.message else ""
        if not message_text and not self.files:
            raise ValueError("Message or files required")
        return self


# -----------------------------------------------------------------------------
# Settings Schemas
# -----------------------------------------------------------------------------


class UpdateSettingsRequest(BaseModel):
    """Schema for PATCH /api/users/me/settings."""

    custom_instructions: str | None = Field(None, max_length=2000)
