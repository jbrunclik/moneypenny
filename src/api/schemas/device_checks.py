"""Device check runner schemas: a run's results and the fixture conversation."""

from enum import StrEnum
from typing import Annotated, Any

from pydantic import AwareDatetime, Field, field_validator

from src.api.schemas.base import QueryModel, RequestModel, ResponseModel, parse_int

DEVICE_CHECK_RUNS_DEFAULT_LIMIT = 20
DEVICE_CHECK_RUNS_MAX_LIMIT = 100

# A measurement is one number, flag or short label - never nested data
type MeasurementValue = float | bool | Annotated[str, Field(max_length=200)] | None
type Measurements = Annotated[dict[str, MeasurementValue], Field(max_length=40)]


class DeviceCheckStatus(StrEnum):
    """How a scenario ended."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"  # e.g. no software keyboard on a desktop
    ERROR = "error"  # the scenario itself threw


class DeviceCheckScenarioResult(RequestModel):
    """One scenario of a run, with what it measured."""

    id: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=120)
    status: DeviceCheckStatus
    duration_ms: int = Field(..., ge=0)
    measurements: Measurements = Field(default_factory=dict)
    notes: list[Annotated[str, Field(max_length=300)]] = Field(default_factory=list, max_length=10)


class DeviceCheckRunRequest(RequestModel):
    """A finished run, sent once by the runner."""

    build_marker: str | None = Field(None, max_length=32, description="The [kbN] marker")
    app_version: str | None = Field(None, max_length=64)
    standalone: bool = Field(..., description="Installed PWA (not a browser tab)")
    ua_summary: str = Field(..., min_length=1, max_length=120, description="e.g. iOS 26.1 · Safari")
    environment: Measurements = Field(default_factory=dict)
    scenarios: list[DeviceCheckScenarioResult] = Field(..., min_length=1, max_length=50)
    started_at: AwareDatetime
    finished_at: AwareDatetime


class DeviceCheckScenario(ResponseModel):
    id: str
    title: str
    status: DeviceCheckStatus
    duration_ms: int
    measurements: dict[str, float | bool | str | None]
    notes: list[str]


class DeviceCheckRun(ResponseModel):
    """A stored run."""

    id: str
    build_marker: str | None
    app_version: str | None
    standalone: bool
    ua_summary: str
    environment: dict[str, float | bool | str | None]
    scenarios: list[DeviceCheckScenario]
    passed: int
    failed: int = Field(..., description="Failed or errored scenarios")
    skipped: int
    started_at: str
    finished_at: str
    created_at: str


class DeviceCheckRunsQuery(QueryModel):
    limit: int = Field(
        default=DEVICE_CHECK_RUNS_DEFAULT_LIMIT,
        description=f"Runs to return (clamped to 1..{DEVICE_CHECK_RUNS_MAX_LIMIT})",
    )

    @field_validator("limit", mode="before")
    @classmethod
    def _limit(cls, value: Any) -> Any:
        return parse_int(value, DEVICE_CHECK_RUNS_DEFAULT_LIMIT, 1, DEVICE_CHECK_RUNS_MAX_LIMIT)


class DeviceCheckRunsResponse(ResponseModel):
    runs: list[DeviceCheckRun] = Field(..., description="Newest first")


class DeviceCheckFixtureResponse(ResponseModel):
    """The throwaway conversation a run scrolls through."""

    conversation_id: str
    message_count: int
