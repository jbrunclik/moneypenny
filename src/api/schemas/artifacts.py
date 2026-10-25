"""Artifact schemas: one version's HTML and the artifact's saved state."""

from typing import Any

from pydantic import Field

from src.api.schemas.base import RequestModel, ResponseModel


class ArtifactVersionResponse(ResponseModel):
    """One version of an artifact, with the artifact's current saved state."""

    id: str = Field(description="Artifact id")
    version: int = Field(description="Version number")
    title: str = Field(description="Artifact title")
    html: str = Field(description="The version's HTML (rendered in the sandboxed frame)")
    state: Any = Field(
        default=None,
        description="JSON value the artifact saved through the bridge (all versions)",
    )


class ArtifactStateRequest(RequestModel):
    """Replace an artifact's saved state (null clears it)."""

    state: Any = Field(description="Any JSON value; null clears it")
