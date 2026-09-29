"""Agent, execution and approval -> API response dict converters."""

from __future__ import annotations

from typing import Any

from src.agent.daily_briefing import resolve_agent_system_prompt
from src.db.models import Agent, AgentExecution, ApprovalRequest, db
from src.utils.datetime_utils import to_utc_iso


def agent_to_response(
    agent: Agent,
    unread_count: int = 0,
    has_pending_approval: bool = False,
    has_error: bool = False,
    last_execution_status: str | None = None,
    daily_spending: float | None = None,
) -> dict[str, Any]:
    """Convert an Agent object to response dict."""
    # Get daily spending if not provided
    if daily_spending is None:
        daily_spending = db.get_agent_daily_spending(agent.id)

    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description,
        "system_prompt": agent.system_prompt,
        "schedule": agent.schedule,
        "timezone": agent.timezone,
        "enabled": agent.enabled,
        "tool_permissions": agent.tool_permissions,
        "model": agent.model,
        "conversation_id": agent.conversation_id,
        "last_run_at": to_utc_iso(agent.last_run_at) if agent.last_run_at else None,
        "next_run_at": to_utc_iso(agent.next_run_at) if agent.next_run_at else None,
        "created_at": to_utc_iso(agent.created_at),
        "updated_at": to_utc_iso(agent.updated_at),
        "budget_limit": agent.budget_limit,
        "fresh_context": agent.fresh_context,
        "system_type": agent.system_type,
        # Resolved prompt for display: equals system_prompt unless the
        # agent is system-managed and on the stock (NULL) prompt
        "effective_system_prompt": resolve_agent_system_prompt(agent),
        "daily_spending": daily_spending,
        "has_pending_approval": has_pending_approval,
        "has_error": has_error,
        "unread_count": unread_count,
        "last_execution_status": last_execution_status,
    }


def execution_to_response(execution: AgentExecution) -> dict[str, Any]:
    """Convert an AgentExecution object to response dict."""
    return {
        "id": execution.id,
        "agent_id": execution.agent_id,
        "status": execution.status,
        "trigger_type": execution.trigger_type,
        "triggered_by_agent_id": execution.triggered_by_agent_id,
        "started_at": to_utc_iso(execution.started_at),
        "completed_at": to_utc_iso(execution.completed_at) if execution.completed_at else None,
        "error_message": execution.error_message,
    }


def approval_to_response(approval: ApprovalRequest, agent_name: str) -> dict[str, Any]:
    """Convert an ApprovalRequest object to response dict."""
    return {
        "id": approval.id,
        "agent_id": approval.agent_id,
        "agent_name": agent_name,
        "tool_name": approval.tool_name,
        "tool_args": approval.tool_args,
        "description": approval.description,
        "status": approval.status,
        "created_at": to_utc_iso(approval.created_at),
        "resolved_at": to_utc_iso(approval.resolved_at) if approval.resolved_at else None,
    }
