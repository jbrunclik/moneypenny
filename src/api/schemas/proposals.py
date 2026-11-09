"""Proposal cards: what Moneypenny asks the user's yes for (docs/features/proposals.md)."""

from typing import Literal

from pydantic import Field

from src.api.schemas.base import RequestModel, ResponseModel


class ProposalOptionResponse(ResponseModel):
    """One choice on a proposal card (its payload stays on the server)."""

    label: str
    description: str = ""


class ProposalResponse(ResponseModel):
    """A card awaiting (or past) the user's answer."""

    id: str
    kind: str = Field(description="schedule_item, create_agent, edit_agent, ...")
    summary: str = Field(description="What it does, in a line")
    details: dict[str, str] = Field(default_factory=dict, description="Label -> value rows")
    options: list[ProposalOptionResponse]
    state: Literal["pending", "approved", "declined", "expired", "superseded", "failed"]
    chosen: int | None = Field(default=None, description="The option picked")
    result: str | None = Field(default=None, description="What applying did, or why it failed")


class ApproveProposalRequest(RequestModel):
    """Approving a card: which of its options (0 when it has one)."""

    choice: int = Field(default=0, ge=0, description="The option's index")
