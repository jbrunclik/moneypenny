"""Row -> dataclass converters shared by the agent mixins."""

from __future__ import annotations

import json
import sqlite3

from src.config import Config
from src.db.models.dataclasses import Agent, AgentExecution, ApprovalRequest
from src.db.models.timestamps import from_db, from_db_or_none


def row_to_agent(row: sqlite3.Row) -> Agent:
    """Convert a database row to an Agent object."""
    tool_permissions = None
    if row["tool_permissions"]:
        tool_permissions = json.loads(row["tool_permissions"])

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
        created_at=from_db(row["created_at"], "utc"),
        updated_at=from_db(row["updated_at"], "utc"),
        last_run_at=from_db_or_none(row["last_run_at"], "utc"),
        next_run_at=from_db_or_none(row["next_run_at"], "utc"),
        last_viewed_at=from_db_or_none(row["last_viewed_at"], "local"),
        budget_limit=row["budget_limit"],
        fresh_context=bool(row["fresh_context"]),
        system_type=row["system_type"],
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
        created_at=from_db(row["created_at"], "utc"),
        resolved_at=from_db_or_none(row["resolved_at"], "utc"),
        expires_at=from_db_or_none(row["expires_at"], "utc"),
    )


def row_to_execution(row: sqlite3.Row) -> AgentExecution:
    """Convert a database row to an AgentExecution object."""
    return AgentExecution(
        id=row["id"],
        agent_id=row["agent_id"],
        status=row["status"],
        trigger_type=row["trigger_type"],
        triggered_by_agent_id=row["triggered_by_agent_id"],
        started_at=from_db(row["started_at"], "utc"),
        completed_at=from_db_or_none(row["completed_at"], "utc"),
        error_message=row["error_message"],
    )
