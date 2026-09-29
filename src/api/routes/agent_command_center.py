"""Agents command center route: dashboard aggregation and weekly stats."""

from __future__ import annotations

from typing import Any

from src.api.helpers.agent_responses import (
    agent_to_response,
    approval_to_response,
    execution_to_response,
)
from src.api.routes.agents import api
from src.api.schemas import CommandCenterResponse
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import User, db
from src.utils.costs import convert_currency, format_cost
from src.utils.logging import get_logger

logger = get_logger(__name__)


@api.route("/agents/command-center", methods=["GET"])
@api.output(CommandCenterResponse)
@api.doc(responses=[401])
@require_auth
def get_command_center(user: User) -> dict[str, Any]:
    """Get command center dashboard data.

    Returns aggregated data for the agents command center:
    - agents: All agents with unread counts and pending status
    - pending_approvals: All pending approval requests
    - recent_executions: Recent execution history
    - total_unread: Total unread messages across all agents
    - agents_waiting: Number of agents blocked on approval
    """
    logger.debug("Fetching command center data", extra={"user_id": user.id})

    data = db.get_command_center_data(user.id)

    # Convert to response format
    agents_response = []
    for agent_data in data["agents"]:
        agents_response.append(
            agent_to_response(
                agent_data["agent"],
                agent_data["unread_count"],
                agent_data["has_pending_approval"],
                agent_data["has_error"],
                agent_data["last_execution_status"],
            )
        )

    approvals_response = []
    for approval_data in data["pending_approvals"]:
        approvals_response.append(
            approval_to_response(
                approval_data["approval"],
                approval_data["agent_name"],
            )
        )

    executions_response = [execution_to_response(e) for e in data["recent_executions"]]

    # Observability: runs + cost over the trailing week, per agent and total
    raw_stats = db.get_agent_observability_stats(user.id, days=7)
    per_agent = []
    total_runs = total_completed = total_failed = 0
    total_cost_usd = 0.0
    for agent_id, stats in raw_stats["per_agent"].items():
        cost_display = format_cost(
            convert_currency(stats["cost_usd"], Config.COST_CURRENCY), Config.COST_CURRENCY
        )
        per_agent.append({"agent_id": agent_id, "cost_display": cost_display, **stats})
        total_runs += stats["runs"]
        total_completed += stats["completed"]
        total_failed += stats["failed"]
        total_cost_usd += stats["cost_usd"]

    stats_block = {
        "days": raw_stats["days"],
        "total_runs": total_runs,
        "total_completed": total_completed,
        "total_failed": total_failed,
        "total_cost_usd": total_cost_usd,
        "total_cost_display": format_cost(
            convert_currency(total_cost_usd, Config.COST_CURRENCY), Config.COST_CURRENCY
        ),
        "per_agent": per_agent,
    }

    return {
        "agents": agents_response,
        "pending_approvals": approvals_response,
        "recent_executions": executions_response,
        "total_unread": data["total_unread"],
        "agents_waiting": data["agents_waiting"],
        "agents_with_errors": data["agents_with_errors"],
        "stats": stats_block,
    }
