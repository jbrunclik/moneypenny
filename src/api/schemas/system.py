"""System schemas: models, upload config, version and health."""

from __future__ import annotations

from pydantic import Field

from src.api.schemas.base import ResponseModel


class ModelResponse(ResponseModel):
    """Available model info."""

    id: str
    name: str
    short_name: str = Field(
        ..., description="Short display name for compact UI (e.g., 'Fast', 'Advanced')"
    )


class ModelsListResponse(ResponseModel):
    """List of available models."""

    models: list[ModelResponse]
    default: str = Field(..., description="Default model ID")


class UploadConfigResponse(ResponseModel):
    """File upload configuration."""

    maxFileSize: int = Field(..., description="Maximum file size in bytes")  # noqa: N815
    maxVideoFileSize: int = Field(..., description="Maximum video file size in bytes")  # noqa: N815
    maxFilesPerMessage: int = Field(..., description="Maximum files per message")  # noqa: N815
    allowedFileTypes: list[str] = Field(..., description="Allowed MIME types")  # noqa: N815


class VersionResponse(ResponseModel):
    """App version info."""

    version: str | None = Field(default=None, description="App version (JS bundle hash)")


class HealthResponse(ResponseModel):
    """Liveness probe response."""

    status: str
    version: str | None = None


class HealthCheckDetail(ResponseModel):
    """Individual health check result."""

    status: str
    message: str | None = None


class ReadinessResponse(ResponseModel):
    """Readiness probe response."""

    status: str = Field(..., description="'ready' or 'not_ready'")
    checks: dict[str, HealthCheckDetail]
    version: str | None = None
