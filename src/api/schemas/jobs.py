"""Jobs: every scheduled item and standing job in one list (standing chats phase 3)."""

from typing import Literal

from pydantic import Field

from src.api.schemas.agents import ApprovalRequestResponse
from src.api.schemas.base import ResponseModel, Timestamp
from src.api.schemas.schedules import ItemKindField

JobArea = Literal["agents", "sports", "language", "chat"]


class JobRunResponse(ResponseModel):
    """One run of a standing job (its audit trail)."""

    status: str = Field(description="running, completed, failed, waiting_approval")
    trigger_type: str = Field(description="scheduled, manual, agent_trigger")
    started_at: Timestamp
    error: str | None = Field(default=None, description="Why it failed, shortened")


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
    editable: bool = Field(description="Opens in the agent editor")
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
    pending_approvals: list[ApprovalRequestResponse]
    stats: JobStatsBlock
    total_unread: int = 0
    jobs_waiting: int = Field(default=0, description="Jobs waiting for an approval")
    jobs_with_errors: int = Field(default=0, description="Jobs whose last run failed")
