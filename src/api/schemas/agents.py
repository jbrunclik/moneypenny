"""Autonomous agent, approval, execution, command center and AI-assist schemas."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.config import Config


class AgentStatus(StrEnum):
    """Status of an agent execution."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_APPROVAL = "waiting_approval"


class AgentTriggerType(StrEnum):
    """How an agent execution was triggered."""

    SCHEDULED = "scheduled"
    MANUAL = "manual"
    AGENT_TRIGGER = "agent_trigger"


class ApprovalStatus(StrEnum):
    """Status of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class CreateAgentRequest(BaseModel):
    """Schema for POST /api/agents."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    system_prompt: str | None = Field(None, max_length=10000)
    schedule: str | None = Field(
        None,
        description="Cron expression (e.g., '0 9 * * *' for daily at 9am)",
    )
    timezone: str = Field(default="UTC", description="IANA timezone for schedule")
    tool_permissions: list[str] | None = Field(None, description="List of allowed tool names")
    enabled: bool = Field(default=True)
    model: str | None = Field(None, description="LLM model for the agent (defaults to Fast)")
    budget_limit: float | None = Field(
        None, ge=0, description="Daily budget limit in USD (null = unlimited)"
    )
    fresh_context: bool = Field(
        default=True,
        description="Run each execution without prior conversation history",
    )

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str | None) -> str | None:
        """Validate model is in available models list."""
        if v is not None and v not in Config.MODELS:
            models = list(Config.MODELS.keys())
            raise ValueError(f"Invalid model. Choose from: {models}")
        return v


class UpdateAgentRequest(BaseModel):
    """Schema for PATCH /api/agents/<id>."""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    system_prompt: str | None = Field(None, max_length=10000)
    schedule: str | None = None
    timezone: str | None = None
    tool_permissions: list[str] | None = None
    enabled: bool | None = None
    model: str | None = None
    budget_limit: float | None = None  # Use None as "not provided", explicit 0 = unlimited
    fresh_context: bool | None = None

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str | None) -> str | None:
        """Validate model is in available models list."""
        if v is not None and v not in Config.MODELS:
            models = list(Config.MODELS.keys())
            raise ValueError(f"Invalid model. Choose from: {models}")
        return v


class AgentResponse(BaseModel):
    """Agent information."""

    id: str
    name: str
    description: str | None = None
    system_prompt: str | None = None
    schedule: str | None = None
    timezone: str
    enabled: bool
    tool_permissions: list[str] | None = None
    model: str = Field(..., description="LLM model for the agent")
    conversation_id: str | None = None
    last_run_at: str | None = None
    next_run_at: str | None = None
    created_at: str
    updated_at: str
    budget_limit: float | None = Field(
        None, description="Daily budget limit in USD (null = unlimited)"
    )
    fresh_context: bool = Field(
        default=False,
        description="Run each execution without prior conversation history",
    )
    system_type: str | None = Field(
        default=None,
        description="System-managed agent marker (e.g. 'daily_briefing'); null for regular agents",
    )
    effective_system_prompt: str | None = Field(
        default=None,
        description="Resolved prompt: the stock default for system-managed agents on a NULL prompt",
    )
    daily_spending: float = Field(default=0, description="Today's spending in USD")
    has_pending_approval: bool = Field(
        default=False, description="Whether agent is blocked waiting for approval"
    )
    has_error: bool = Field(default=False, description="Whether the last execution failed")
    unread_count: int = Field(
        default=0, description="Number of unread messages in agent conversation"
    )
    last_execution_status: str | None = Field(
        default=None, description="Status of the most recent execution (completed, failed, etc.)"
    )


class AgentsListResponse(BaseModel):
    """List of agents."""

    agents: list[AgentResponse]


class ApprovalRequestResponse(BaseModel):
    """Approval request information."""

    id: str
    agent_id: str
    agent_name: str = Field(..., description="Name of the agent requesting approval")
    tool_name: str
    tool_args: dict[str, Any] | None = None
    description: str
    status: ApprovalStatus
    created_at: str
    resolved_at: str | None = None


class ApprovalDecisionRequest(BaseModel):
    """Schema for POST /api/approvals/<id>/approve or reject."""


class AgentExecutionResponse(BaseModel):
    """Agent execution record."""

    id: str
    agent_id: str
    status: AgentStatus
    trigger_type: AgentTriggerType
    triggered_by_agent_id: str | None = None
    started_at: str
    completed_at: str | None = None
    error_message: str | None = None


class AgentExecutionsListResponse(BaseModel):
    """List of agent executions."""

    executions: list[AgentExecutionResponse]


class AgentWindowStats(BaseModel):
    """One agent's runs and cost over the stats window."""

    agent_id: str
    runs: int = 0
    completed: int = 0
    failed: int = 0
    waiting_approval: int = 0
    cost_usd: float = 0.0
    cost_display: str = Field(default="", description="Cost formatted in the display currency")
    input_tokens: int = 0
    output_tokens: int = 0


class AgentStatsBlock(BaseModel):
    """Aggregated observability stats for the command center."""

    days: int = 7
    total_runs: int = 0
    total_completed: int = 0
    total_failed: int = 0
    total_cost_usd: float = 0.0
    total_cost_display: str = ""
    per_agent: list[AgentWindowStats] = Field(default_factory=list)


class CommandCenterResponse(BaseModel):
    """Complete command center dashboard data."""

    agents: list[AgentResponse] = Field(
        ..., description="All agents with unread counts and pending status"
    )
    pending_approvals: list[ApprovalRequestResponse] = Field(
        default_factory=list, description="All pending approval requests"
    )
    recent_executions: list[AgentExecutionResponse] = Field(
        default_factory=list, description="Recent execution history across all agents"
    )
    total_unread: int = Field(default=0, description="Total unread messages across all agents")
    agents_waiting: int = Field(default=0, description="Number of agents blocked on approval")
    stats: AgentStatsBlock = Field(
        default_factory=AgentStatsBlock,
        description="Run/cost aggregates over the trailing window",
    )
    agents_with_errors: int = Field(
        default=0, description="Number of agents whose last execution failed"
    )


class TriggerAgentResponse(BaseModel):
    """Response from manually triggering an agent."""

    execution: AgentExecutionResponse
    message: str = Field(default="Agent triggered", description="Status message")


class PendingApprovalsResponse(BaseModel):
    """List of pending approval requests."""

    pending_approvals: list[ApprovalRequestResponse] = Field(
        default_factory=list, description="All pending approval requests"
    )


class AgentConversationSyncData(BaseModel):
    """Sync data for an agent's conversation."""

    message_count: int = Field(..., description="Total number of messages in conversation")
    updated_at: str = Field(..., description="Conversation updated_at timestamp in ISO format")


class AgentConversationSyncResponse(BaseModel):
    """Response from agent conversation sync endpoint for real-time synchronization."""

    conversation: AgentConversationSyncData | None = Field(
        default=None, description="Agent conversation state, or null if no conversation exists"
    )
    server_time: str = Field(..., description="Server timestamp in ISO format")


class ParseScheduleRequest(BaseModel):
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


class ParseScheduleResponse(BaseModel):
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


class EnhancePromptRequest(BaseModel):
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


class EnhancePromptResponse(BaseModel):
    """Response from prompt enhancement endpoint."""

    enhanced_prompt: str | None = Field(
        default=None,
        description="AI-enhanced system prompt",
    )
    error: str | None = Field(
        default=None,
        description="Error message if enhancement failed",
    )
