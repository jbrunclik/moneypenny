"""Browser error report schema."""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from src.api.schemas.base import RequestModel


class ClientErrorKind(StrEnum):
    """How the browser caught the error."""

    ERROR = "error"  # window "error": an uncaught exception
    UNHANDLED_REJECTION = "unhandled_rejection"
    LOGGED = "logged"  # handled, but logged at error level
    LAYOUT = "layout"  # a layout invariant failed (web/src/core/layout-checks.ts)


class LayoutInvariant(StrEnum):
    """Which layout check failed (docs/ui/mobile-and-pwa.md, "Layout checks")."""

    COMPOSER_GAP = "composer_gap"  # composer bottom off the keyboard top
    STRANDED_PAN = "stranded_pan"  # the window stayed scrolled after settling
    INSET_MISMATCH = "inset_mismatch"  # applied --keyboard-inset off the formula
    ANCHOR_DRIFT = "anchor_drift"  # an anchored turn left its anchor (keyboard)
    SCROLL_BOTTOM_MISS = "scroll_bottom_miss"  # a scroll to the bottom fell short


_Token = Annotated[str, StringConstraints(min_length=1, max_length=32, pattern=r"^[a-z0-9_.-]+$")]


class LayoutCheckDetail(RequestModel):
    """What a failed layout check saw: numbers only, never anything on screen."""

    invariant: LayoutInvariant
    shape: _Token = Field(..., description="Which way it failed, e.g. gap or overlap")
    build_marker: _Token = Field(..., description="The keyboard code's [kbN] marker")
    standalone: bool = Field(..., description="Home-screen app, not a browser tab")
    ios_version: str | None = Field(None, max_length=16)
    measurements: dict[_Token, float] = Field(
        ..., max_length=16, description="Viewport numbers in CSS px"
    )


class ClientErrorReport(RequestModel):
    """One error from the browser. Long text is accepted and cut server-side."""

    kind: ClientErrorKind
    message: str = Field(..., min_length=1, max_length=5000)
    stack: str | None = Field(None, max_length=20000)
    path: str | None = Field(None, max_length=2000, description="Route path, no query")
    app_version: str | None = Field(None, max_length=64)
    layout: LayoutCheckDetail | None = Field(None, description="Only for kind layout")

    @model_validator(mode="after")
    def _layout_detail_iff_layout_kind(self) -> Self:
        if (self.kind == ClientErrorKind.LAYOUT) != (self.layout is not None):
            raise ValueError("layout detail goes with kind layout, and only with it")
        return self
