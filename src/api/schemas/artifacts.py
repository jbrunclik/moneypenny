"""Artifact schemas: one version's HTML and the artifact's saved state."""

from typing import Any

from pydantic import BaseModel, Field


class ArtifactVersionResponse(BaseModel):
    """One version of an artifact, with the artifact's current saved state."""

    id: str = Field(description="Artifact id")
    version: int = Field(description="Version number")
    title: str = Field(description="Artifact title")
    html: str = Field(description="The version's HTML (rendered in the sandboxed frame)")
    state: dict[str, Any] | None = Field(
        default=None, description="State the artifact saved through the bridge (all versions)"
    )


class ArtifactStateRequest(BaseModel):
    """Replace an artifact's saved state (null clears it)."""

    state: dict[str, Any] | None = Field(description="JSON state; null clears it")
