"""Proposal cards: what Moneypenny asks the user's yes for (docs/features/proposals.md)."""

from typing import Literal

from pydantic import Field

from src.api.schemas.base import RequestModel, ResponseModel
from src.api.schemas.programs import SetupFieldChange


class ProposalOptionResponse(ResponseModel):
    """One choice on a proposal card (its payload stays on the server)."""

    label: str
    description: str = ""


class ProposalDetailResponse(ResponseModel):
    """One label/value row on a card (a list: JSON objects lose their order)."""

    label: str
    value: str


class ResearchRatesResponse(ResponseModel):
    """What the editor's live estimate is computed from (estimate.py)."""

    base_minutes: float
    per_wave_minutes: float
    parallelism: int
    base_czk: float
    per_item_czk: float


class ResearchPlanResponse(ResponseModel):
    """A deep_research card's plan, for its editor: the questions that run
    (the edited ones once started) and what the estimate needs."""

    question: str
    context: str
    sub_questions: list[str]
    rates: ResearchRatesResponse
    autostart: bool = Field(description="An explicit request: Start after a countdown")
    kind: Literal["initial", "followup"]


class ProposalResponse(ResponseModel):
    """A card awaiting (or past) the user's answer."""

    id: str
    kind: str = Field(description="schedule_item, create_agent, edit_agent, ...")
    summary: str = Field(description="What it does, in a line")
    details: list[ProposalDetailResponse] = Field(
        default_factory=list, description="Label/value rows, in order"
    )
    options: list[ProposalOptionResponse]
    state: Literal["pending", "applying", "approved", "declined", "expired", "superseded", "failed"]
    chosen: int | None = Field(default=None, description="The option picked")
    result: str | None = Field(default=None, description="What applying did, or why it failed")
    research: ResearchPlanResponse | None = Field(
        default=None, description="deep_research only: the plan its editor shows"
    )
    changes: list[SetupFieldChange] | None = Field(
        default=None,
        description="program_setup / custom_instructions: what changes, one row per field",
    )


class ApproveProposalRequest(RequestModel):
    """Approving a card: which of its options (0 when it has one)."""

    choice: int = Field(default=0, ge=0, description="The option's index")
