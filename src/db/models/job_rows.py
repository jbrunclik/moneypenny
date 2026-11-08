"""Row -> dataclass converters for job runs and approvals."""

from __future__ import annotations

import json
import sqlite3

from src.db.models.dataclasses import ApprovalRequest, JobRun
from src.db.models.timestamps import from_db, from_db_or_none


def row_to_approval_request(row: sqlite3.Row) -> ApprovalRequest:
    """Convert a database row to an ApprovalRequest object."""
    tool_args = json.loads(row["tool_args"]) if row["tool_args"] else None
    return ApprovalRequest(
        id=row["id"],
        item_id=row["item_id"],
        user_id=row["user_id"],
        tool_name=row["tool_name"],
        tool_args=tool_args,
        description=row["description"],
        status=row["status"],
        created_at=from_db(row["created_at"]),
        resolved_at=from_db_or_none(row["resolved_at"]),
        expires_at=from_db_or_none(row["expires_at"]),
    )


def row_to_job_run(row: sqlite3.Row) -> JobRun:
    """Convert a database row to a JobRun object."""
    return JobRun(
        id=row["id"],
        item_id=row["item_id"],
        status=row["status"],
        trigger_type=row["trigger_type"],
        triggered_by_job_id=row["triggered_by_job_id"],
        started_at=from_db(row["started_at"]),
        completed_at=from_db_or_none(row["completed_at"]),
        error_message=row["error_message"],
    )
