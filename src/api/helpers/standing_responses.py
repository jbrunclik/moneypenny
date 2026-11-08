"""Standing chat, job run and approval -> API data (the job editor and approvals)."""

from __future__ import annotations

from typing import Any

from src.agent.daily_briefing import effective_instructions
from src.config import Config
from src.db.models import ApprovalRequest, JobRun, StandingChat, db
from src.db.models.scheduled_items import NEVER_RUN_AT
from src.utils.clock import to_api


def standing_to_response(chat: StandingChat) -> dict[str, Any]:
    """A standing chat and its job, as the editor shows it."""
    job = chat.job
    runs_soon = chat.enabled and job.next_run_at < NEVER_RUN_AT
    last_status = db.get_last_execution_status(chat.id)
    return {
        "id": chat.id,
        "name": chat.name,
        "description": chat.description,
        "instructions": chat.instructions,
        # A built-in on its stock (null) prompt shows the prompt in force
        "effective_instructions": effective_instructions(chat.instructions, chat.standing_type),
        "schedule": job.schedule,
        "timezone": job.timezone or "UTC",
        "enabled": chat.enabled,
        "grants": chat.grants,
        "model": job.model or Config.DEFAULT_MODEL,
        "conversation_id": chat.conversation_id,
        "last_run_at": to_api(chat.last_run_at) if chat.last_run_at else None,
        "next_run_at": to_api(job.next_run_at) if runs_soon else None,
        "created_at": to_api(job.created_at),
        "updated_at": to_api(chat.updated_at),
        "budget_usd": job.budget_usd,
        "fresh_context": job.fresh_context,
        "standing_type": chat.standing_type,
        "spend_today_usd": db.job_spend_today(chat.id),
        "has_pending_approval": db.has_pending_approval(chat.id),
        "unread_count": db.standing_unread_count(chat.id),
        "last_run_status": last_status,
    }


def run_to_response(run: JobRun) -> dict[str, Any]:
    """One run of a job, in full."""
    return {
        "id": run.id,
        "item_id": run.item_id,
        "status": run.status,
        "trigger_type": run.trigger_type,
        "triggered_by_job_id": run.triggered_by_job_id,
        "started_at": to_api(run.started_at),
        "completed_at": to_api(run.completed_at) if run.completed_at else None,
        "error_message": run.error_message,
    }


def approval_to_response(approval: ApprovalRequest, job_name: str) -> dict[str, Any]:
    """A run's approval request."""
    return {
        "id": approval.id,
        "item_id": approval.item_id,
        "job_name": job_name,
        "tool_name": approval.tool_name,
        "tool_args": approval.tool_args,
        "description": approval.description,
        "status": approval.status,
        "created_at": to_api(approval.created_at),
        "resolved_at": to_api(approval.resolved_at) if approval.resolved_at else None,
    }
