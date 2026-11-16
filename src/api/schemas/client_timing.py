"""Startup timing reports from the browser (POST /api/client-timing)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from src.api.schemas.base import RequestModel

# A stage mark: ms since navigation start. A day bounds a phone that went to
# the background mid-start (such loads come flagged `hidden`)
_Mark = Annotated[int, Field(ge=0, le=86_400_000)] | None


class BootMarks(RequestModel):
    """How long the startup stages took (ms since navigation start)."""

    model_config = ConfigDict(extra="forbid")

    response_end_ms: _Mark = None
    dom_content_loaded_ms: _Mark = None
    script_ms: _Mark = None
    auth_ms: _Mark = None
    data_ms: _Mark = None
    route_ms: _Mark = None
    ready_ms: _Mark = None


class ClientTimingReport(RequestModel):
    """One page load's startup timing, sent once the app is ready."""

    model_config = ConfigDict(extra="forbid")

    marks: BootMarks
    standalone: bool = Field(..., description="Home-screen app, not a browser tab")
    viewport: Literal["mobile", "desktop"] = Field(..., description="Under 768 px: mobile")
    connection: str | None = Field(None, max_length=16, description="effectiveType, e.g. 4g")
    app_version: str | None = Field(None, max_length=64)
    route: str = Field(..., min_length=1, max_length=24, description="The initial route type")
    hidden: bool = Field(False, description="The page went to the background before it was ready")
