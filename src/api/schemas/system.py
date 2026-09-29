"""System schemas: models, upload config, version and health."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelResponse(BaseModel):
    """Available model info."""

    id: str
    name: str
    short_name: str = Field(
        ..., description="Short display name for compact UI (e.g., 'Fast', 'Advanced')"
    )


class ModelsListResponse(BaseModel):
    """List of available models."""

    models: list[ModelResponse]
    default: str = Field(..., description="Default model ID")


class UploadConfigResponse(BaseModel):
    """File upload configuration."""

    maxFileSize: int = Field(..., description="Maximum file size in bytes")
    maxVideoFileSize: int = Field(..., description="Maximum video file size in bytes")
    maxFilesPerMessage: int = Field(..., description="Maximum files per message")
    allowedFileTypes: list[str] = Field(..., description="Allowed MIME types")


class VersionResponse(BaseModel):
    """App version info."""

    version: str | None = Field(default=None, description="App version (JS bundle hash)")


class HealthResponse(BaseModel):
    """Liveness probe response."""

    status: str
    version: str | None = None


class HealthCheckDetail(BaseModel):
    """Individual health check result."""

    status: str
    message: str | None = None


class ReadinessResponse(BaseModel):
    """Readiness probe response."""

    status: str = Field(..., description="'ready' or 'not_ready'")
    checks: dict[str, HealthCheckDetail]
    version: str | None = None
