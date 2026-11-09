"""Row -> dataclass converters for job runs and approvals."""

from __future__ import annotations

import sqlite3

from src.db.models.dataclasses import JobRun
from src.db.models.timestamps import from_db, from_db_or_none


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
