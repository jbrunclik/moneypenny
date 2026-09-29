"""Cost tracking and conversation compaction status schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConversationCostResponse(BaseModel):
    """Cost for a conversation."""

    conversation_id: str
    cost_usd: float
    cost: float = Field(..., description="Cost in display currency")
    currency: str
    formatted: str


class ConversationCompactionResponse(BaseModel):
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


class MessageCostResponse(BaseModel):
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


class ModelCostBreakdown(BaseModel):
    """Cost breakdown by model."""

    total: float
    total_usd: float
    message_count: int
    formatted: str


class MonthlyCostResponse(BaseModel):
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


class MonthCostEntry(BaseModel):
    """Single month in cost history."""

    year: int
    month: int
    total_usd: float
    total: float
    currency: str
    formatted: str
    message_count: int


class CostHistoryResponse(BaseModel):
    """Cost history for a user."""

    user_id: str
    history: list[MonthCostEntry]
