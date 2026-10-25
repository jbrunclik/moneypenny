"""Cost tracking and conversation compaction status schemas."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from src.api.schemas.base import QueryModel, ResponseModel, parse_int


class ConversationCostResponse(ResponseModel):
    """Cost for a conversation."""

    conversation_id: str
    cost_usd: float
    cost: float = Field(..., description="Cost in display currency")
    currency: str
    formatted: str


class ConversationCompactionResponse(ResponseModel):
    """How the next turn compacts a conversation's history for the model."""

    conversation_id: str
    active: bool = Field(..., description="Whether older messages are replaced by a summary")
    summarized_count: int = Field(..., description="Leading messages replaced by the summary")
    total_count: int = Field(..., description="Messages in the conversation")
    generation: int = Field(
        ..., description="Summarization passes folded into the summary (each loses detail)"
    )
    generation_estimated: bool = Field(
        ..., description="Generation inferred for summaries saved before it was tracked"
    )
    boundary_message_id: str | None = Field(None, description="Last message covered by the summary")
    summary: str | None = Field(None, description="Summary text the model sees")


class MessageCostResponse(ResponseModel):
    """Cost breakdown for a message."""

    message_id: str
    cost_usd: float
    cost: float = Field(..., description="Cost in display currency")
    currency: str
    formatted: str
    input_tokens: int
    output_tokens: int
    model: str
    image_generation_cost_usd: float | None = None
    image_generation_cost: float | None = None
    image_generation_cost_formatted: str | None = None


class ModelCostBreakdown(ResponseModel):
    """Cost breakdown by model."""

    total: float
    total_usd: float
    message_count: int
    formatted: str


class MonthlyCostResponse(ResponseModel):
    """Monthly cost for a user."""

    user_id: str
    year: int
    month: int
    total_usd: float
    total: float = Field(..., description="Total in display currency")
    currency: str
    formatted: str
    message_count: int
    breakdown: dict[str, ModelCostBreakdown]


class MonthCostEntry(ResponseModel):
    """Single month in cost history."""

    year: int
    month: int
    total_usd: float
    total: float
    currency: str
    formatted: str
    message_count: int


class CostHistoryResponse(ResponseModel):
    """Cost history for a user."""

    user_id: str
    history: list[MonthCostEntry]


class MonthlyCostQuery(QueryModel):
    """Query for GET /api/users/me/costs/monthly; a missing or 0 value means this year/month."""

    year: int | None = Field(default=None, ge=0, le=9998)
    month: int | None = Field(default=None, description="1-12")

    @field_validator("year", "month", mode="before")
    @classmethod
    def _parse(cls, value: Any) -> Any:
        return parse_int(value, None)


class CostHistoryQuery(QueryModel):
    """Query for GET /api/users/me/costs/history; a missing or 0 limit means the default."""

    limit: int | None = Field(default=None, ge=0, description="Months (capped)")

    @field_validator("limit", mode="before")
    @classmethod
    def _limit(cls, value: Any) -> Any:
        return parse_int(value, None)
