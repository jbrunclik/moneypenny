"""Row -> dataclass converters shared by the agent mixins."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from src.config import Config
from src.db.models.dataclasses import Agent, AgentExecution, ApprovalRequest


def row_to_agent(row: sqlite3.Row) -> Agent:
    """Convert a database row to an Agent object."""
    tool_permissions = None
    if row["tool_permissions"]:
        tool_permissions = json.loads(row["tool_permissions"])

    # Handle budget_limit column (may not exist in older databases)
    budget_limit = None
    if "budget_limit" in row.keys():
        budget_limit = row["budget_limit"]

    return Agent(
        id=row["id"],
        user_id=row["user_id"],
        conversation_id=row["conversation_id"],
        name=row["name"],
        description=row["description"],
        system_prompt=row["system_prompt"],
        schedule=row["schedule"],
        timezone=row["timezone"] or "UTC",
        enabled=bool(row["enabled"]),
        tool_permissions=tool_permissions,
        model=row["model"] or Config.DEFAULT_MODEL,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        last_run_at=(datetime.fromisoformat(row["last_run_at"]) if row["last_run_at"] else None),
        next_run_at=(datetime.fromisoformat(row["next_run_at"]) if row["next_run_at"] else None),
        last_viewed_at=(
            datetime.fromisoformat(row["last_viewed_at"]) if row["last_viewed_at"] else None
        ),
        budget_limit=budget_limit,
        fresh_context=(bool(row["fresh_context"]) if "fresh_context" in row.keys() else False),
        system_type=(row["system_type"] if "system_type" in row.keys() else None),
    )


def row_to_approval_request(row: sqlite3.Row) -> ApprovalRequest:
    """Convert a database row to an ApprovalRequest object."""
    tool_args = None
    if row["tool_args"]:
        tool_args = json.loads(row["tool_args"])

    return ApprovalRequest(
        id=row["id"],
        agent_id=row["agent_id"],
        user_id=row["user_id"],
        tool_name=row["tool_name"],
        tool_args=tool_args,
        description=row["description"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
        resolved_at=(datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None),
        expires_at=(datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None),
    )


def row_to_execution(row: sqlite3.Row) -> AgentExecution:
    """Convert a database row to an AgentExecution object."""
    return AgentExecution(
        id=row["id"],
        agent_id=row["agent_id"],
        status=row["status"],
        trigger_type=row["trigger_type"],
        triggered_by_agent_id=row["triggered_by_agent_id"],
        started_at=datetime.fromisoformat(row["started_at"]),
        completed_at=(datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None),
        error_message=row["error_message"],
    )
