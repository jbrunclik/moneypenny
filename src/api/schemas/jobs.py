"""Jobs: every scheduled item and standing job in one list, the standing chat
editor's CRUD on /api/jobs, runs and approvals (standing chats phase 3)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator

from src.api.schemas.base import RequestModel, ResponseModel, Timestamp
from src.api.schemas.proposals import ProposalResponse
from src.api.schemas.schedules import ItemKindField
from src.config import Config
from src.constants import AGENT_INSTRUCTIONS_MAX_CHARS, AGENT_NAME_MAX_CHARS

JobArea = Literal["agents", "sports", "language", "chat"]


class JobRunStatus(StrEnum):
    """Status of a job run."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_APPROVAL = "waiting_approval"


class RunProposalResponse(ProposalResponse):
    """A run waiting on the user's card, with the job it belongs to."""

    job_id: str = Field(description="The job whose run asked")
    job_name: str = Field(description="The standing chat's name")
    conversation_id: str = Field(description="The agent's chat (the card shows there too)")
    created_at: Timestamp


class PendingApprovalsResponse(ResponseModel):
    """Runs waiting on the user's card (Command Center's "Needs you")."""

    pending_approvals: list[RunProposalResponse] = Field(default_factory=list)


class JobRunResponse(ResponseModel):
    """One run of a standing job (its audit trail, in the job list)."""

    status: str = Field(description="running, completed, failed, waiting_approval")
    trigger_type: str = Field(description="scheduled, manual, agent_trigger, approval")
    started_at: Timestamp
    error: str | None = Field(default=None, description="Why it failed, shortened")


class JobRunRecordResponse(ResponseModel):
    """One run of a job, in full."""

    id: str
    item_id: str
    status: JobRunStatus
    trigger_type: str = Field(description="scheduled, manual, agent_trigger, approval")
    triggered_by_job_id: str | None = None
    started_at: Timestamp
    completed_at: Timestamp | None = None
    error_message: str | None = None


class JobRunsListResponse(ResponseModel):
    """A job's recent runs, newest first."""

    runs: list[JobRunRecordResponse]


class RunJobResponse(ResponseModel):
    """A run started by hand: its record and what happened."""

    run: JobRunRecordResponse
    message: str


class JobResponse(ResponseModel):
    """One job: a light item set from a chat, or a standing job (an agent)."""

    id: str
    kind: ItemKindField
    standing: bool
    area: JobArea = Field(description="Where its chat lives")
    title: str = Field(description="The agent's name, or the item's text shortened")
    conversation_id: str
    conversation_title: str
    when: str
    ends: str
    status: Literal["active", "paused", "running"]
    paused_reason: str | None = None
    next_run_at: Timestamp | None = Field(default=None, description="None: runs only on demand")
    system_type: str | None = Field(default=None, description="Built-in (daily_briefing)")
    editable: bool = Field(description="Opens in the job editor")
    unread_count: int = 0
    has_pending_approval: bool = False
    cost_7d_display: str | None = None
    runs_7d: int = 0
    recent_runs: list[JobRunResponse] = Field(default_factory=list)


class JobStatsBlock(ResponseModel):
    """The standing jobs' runs and cost over the trailing week."""

    days: int = 7
    total_runs: int = 0
    total_completed: int = 0
    total_failed: int = 0
    total_cost_display: str = ""


class JobsOverviewResponse(ResponseModel):
    """The job list: needs attention first, then soonest."""

    jobs: list[JobResponse]
    pending_approvals: list[RunProposalResponse]
    stats: JobStatsBlock
    total_unread: int = 0
    jobs_waiting: int = Field(default=0, description="Jobs waiting for an approval")
    jobs_with_errors: int = Field(default=0, description="Jobs whose last run failed")


def _known_model(v: str | None) -> str | None:
    if v is not None and v not in Config.MODELS:
        raise ValueError(f"Invalid model. Choose from: {list(Config.MODELS)}")
    return v


class CreateJobRequest(RequestModel):
    """POST /api/jobs: a new standing chat with its job."""

    name: str = Field(..., min_length=1, max_length=AGENT_NAME_MAX_CHARS)
    description: str | None = Field(None, max_length=500)
    instructions: str | None = Field(None, max_length=AGENT_INSTRUCTIONS_MAX_CHARS)
    schedule: str | None = Field(None, description="Cron, e.g. '0 9 * * *'; null = on demand")
    timezone: str = Field(default="UTC", description="IANA timezone for the schedule")
    grants: list[str] | None = Field(
        None, description='Tools it may use; "<tool>:write" lets it change things; null = all'
    )
    enabled: bool = True
    model: str | None = Field(None, description="LLM model (defaults to Fast)")
    budget_usd: float | None = Field(None, ge=0, description="Daily budget in USD (null = none)")
    fresh_context: bool = Field(default=True, description="Each run starts without history")

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str | None) -> str | None:
        """Only the configured models."""
        return _known_model(v)


class UpdateJobRequest(RequestModel):
    """PATCH /api/jobs/<id>: only the fields sent change."""

    name: str | None = Field(None, min_length=1, max_length=AGENT_NAME_MAX_CHARS)
    description: str | None = Field(None, max_length=500)
    instructions: str | None = Field(None, max_length=AGENT_INSTRUCTIONS_MAX_CHARS)
    schedule: str | None = None
    timezone: str | None = None
    grants: list[str] | None = None
    enabled: bool | None = None
    model: str | None = None
    budget_usd: float | None = None
    fresh_context: bool | None = None

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str | None) -> str | None:
        """Only the configured models."""
        return _known_model(v)


class JobDetailResponse(ResponseModel):
    """A standing chat and its job, as the editor shows it."""

    id: str
    name: str
    description: str | None = None
    instructions: str | None = None
    effective_instructions: str | None = Field(
        default=None, description="The instructions in force: a built-in's stock prompt on null"
    )
    schedule: str | None = None
    timezone: str
    enabled: bool
    grants: list[str] = Field(description='Tools it may use, write levels as "<tool>:write"')
    model: str
    conversation_id: str
    last_run_at: Timestamp | None = None
    next_run_at: Timestamp | None = None
    created_at: Timestamp
    updated_at: Timestamp
    budget_usd: float | None = None
    fresh_context: bool
    standing_type: str | None = Field(default=None, description="Built-in marker")
    spend_today_usd: float = 0
    has_pending_approval: bool = False
    unread_count: int = 0
    last_run_status: str | None = None


class JobConversationSyncData(ResponseModel):
    """A standing chat's conversation state."""

    message_count: int
    updated_at: Timestamp


class JobConversationSyncResponse(ResponseModel):
    """Polling a standing chat's conversation for changes."""

    conversation: JobConversationSyncData | None = None
    server_time: Timestamp
