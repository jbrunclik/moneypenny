"""Agent approval routes: list, approve (resumes the agent), reject."""

from __future__ import annotations

from typing import Any

from src.agent.item_scheduler import JobBusyError, run_job_now
from src.api.errors import raise_not_found_error
from src.api.helpers.agent_responses import approval_to_response
from src.api.rate_limiting import rate_limit_conversations
from src.api.routes.agents import api
from src.api.schemas.agents import PendingApprovalsResponse
from src.api.schemas.common import StatusResponse
from src.auth.jwt_auth import require_auth
from src.db.models import User, db
from src.db.models.dataclasses import ApprovalRequest
from src.enums import MessageRole
from src.utils.logging import get_logger

logger = get_logger(__name__)


@api.route("/agents/approvals", methods=["GET"])
@api.output(PendingApprovalsResponse)
@api.doc(responses=[401])
@require_auth
def list_pending_approvals(user: User) -> dict[str, Any]:
    """Get all pending approval requests.

    Returns pending approvals with agent names for display.
    """
    approvals = db.get_pending_approvals(user.id)

    approvals_response = []
    for approval in approvals:
        agent = db.get_agent(approval.agent_id, user.id)
        agent_name = agent.name if agent else "Unknown Agent"
        approvals_response.append(approval_to_response(approval, agent_name))

    return {"pending_approvals": approvals_response}


@api.route("/approvals/<approval_id>/approve", methods=["POST"])
@api.output(StatusResponse)
@api.doc(responses=[401, 404])
@rate_limit_conversations
@require_auth
def approve_request(user: User, approval_id: str) -> dict[str, Any]:
    """Approve a pending approval request.

    Marks the request as approved and resumes the agent execution.
    The agent will continue with a message indicating the action was approved.
    """
    logger.info(
        "Approving request",
        extra={"user_id": user.id, "approval_id": approval_id},
    )

    # First, get the approval request details before resolving
    approval = db.get_approval_request(approval_id, user.id)
    if not approval:
        raise_not_found_error("Approval request")

    # Agents are standing jobs (same id): resume the job
    return _approve_job_request(user, approval_id, approval)


@api.route("/approvals/<approval_id>/reject", methods=["POST"])
@api.output(StatusResponse)
@api.doc(responses=[401, 404])
@rate_limit_conversations
@require_auth
def reject_request(user: User, approval_id: str) -> dict[str, Any]:
    """Reject a pending approval request.

    Marks the request as rejected. The agent will not perform
    the requested action. Adds a rejection message to the conversation.
    """
    logger.info(
        "Rejecting request",
        extra={"user_id": user.id, "approval_id": approval_id},
    )

    # Get the approval details before resolving
    approval = db.get_approval_request(approval_id, user.id)
    if not approval:
        raise_not_found_error("Approval request")

    # The agent's (or the standing job's) conversation
    agent = db.get_agent(approval.agent_id, user.id)
    job = None if agent else db.get_item(approval.agent_id, user.id)
    conversation_id = agent.conversation_id if agent else (job.conversation_id if job else None)

    # Resolve the approval
    resolved = db.resolve_approval(approval_id, user.id, approved=False)
    if not resolved:
        raise_not_found_error("Approval request")

    # Add rejection message to the conversation
    if conversation_id:
        rejection_message = f"[Action rejected: {approval.description}]"
        db.add_message(conversation_id, MessageRole.USER, rejection_message)

    _close_waiting_execution(approval.agent_id, status="failed", error="Action rejected by user")

    return {"status": "rejected"}


def _approve_job_request(user: User, approval_id: str, approval: ApprovalRequest) -> dict[str, str]:
    """Approve a standing job's request and resume its run with the outcome."""
    job = db.get_item(approval.agent_id, user.id)
    if job is None or not job.standing:
        raise_not_found_error("Agent")
    if not db.resolve_approval(approval_id, user.id, approved=True):
        raise_not_found_error("Approval request")
    _close_waiting_execution(job.id, status="completed")
    resume_message = f"[Action approved: {approval.description}]"
    db.add_message(job.conversation_id, MessageRole.USER, resume_message)
    try:
        run_job_now(job, user, message=resume_message)
    except JobBusyError:  # the scheduler is running it: that run sees the approval
        logger.info("Job busy on approval; not resumed", extra={"item_id": job.id})
    except Exception:  # the approval went through: the run's crash is logged, not a 500
        logger.exception("Resumed job run crashed", extra={"item_id": job.id})
    logger.info("Approval processed and job resumed", extra={"approval_id": approval_id})
    return {"status": "approved"}


def _close_waiting_execution(agent_id: str, status: str, error: str | None = None) -> None:
    """Close the agent's run that paused for this approval, if it is the latest."""
    executions = db.get_agent_executions(agent_id, limit=1)
    if executions and executions[0].status == "waiting_approval":
        db.update_execution(executions[0].id, status=status, error_message=error)
