"""AI-assist schemas: natural-language schedule parsing and the prompt enhancer
(the standing chat editor's helpers)."""

from __future__ import annotations

from pydantic import Field

from src.api.schemas.base import RequestModel, ResponseModel


class ParseScheduleRequest(RequestModel):
    """Schema for POST /api/ai-assist/parse-schedule."""

    natural_language: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Natural language description of the schedule (e.g., 'every day at 9am')",
    )
    timezone: str = Field(
        default="UTC",
        description="IANA timezone for interpreting the schedule",
    )


class ParseScheduleResponse(ResponseModel):
    """Response from schedule parsing endpoint."""

    cron: str | None = Field(
        default=None,
        description="Parsed cron expression (5-part format)",
    )
    explanation: str | None = Field(
        default=None,
        description="Human-readable explanation of the schedule",
    )
    error: str | None = Field(
        default=None,
        description="Error message if parsing failed",
    )


class EnhancePromptRequest(RequestModel):
    """Schema for POST /api/ai-assist/enhance-prompt."""

    prompt: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Current system prompt to enhance",
    )
    agent_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Name of the agent (for context)",
    )
    tool_permissions: list[str] | None = Field(
        default=None,
        description=(
            "List of optional tool names the agent can use (excludes always-available tools)."
        ),
    )


class EnhancePromptResponse(ResponseModel):
    """Response from prompt enhancement endpoint."""

    enhanced_prompt: str | None = Field(
        default=None,
        description="AI-enhanced system prompt",
    )
    error: str | None = Field(
        default=None,
        description="Error message if enhancement failed",
    )
