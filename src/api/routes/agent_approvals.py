"""Agent approval routes: list, approve (resumes the agent), reject."""

from __future__ import annotations

from typing import Any

from src.api.errors import raise_not_found_error
from src.api.helpers.agent_responses import approval_to_response
from src.api.rate_limiting import rate_limit_conversations
from src.api.routes.agents import api
from src.api.schemas.agents import PendingApprovalsResponse
from src.api.schemas.common import MessageRole, StatusResponse
from src.auth.jwt_auth import require_auth
from src.db.models import User, db
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

    # Get the agent
    agent = db.get_agent(approval.agent_id, user.id)
    if not agent:
        raise_not_found_error("Agent")

    # Resolve the approval
    resolved = db.resolve_approval(approval_id, user.id, approved=True)
    if not resolved:
        raise_not_found_error("Approval request")

    # Resume agent execution with a message about the approved action
    # Create a new execution record for the resumed run
    execution = db.create_execution(
        agent_id=agent.id,
        trigger_type="manual",  # Resuming after approval
    )

    # Execute the agent with a message indicating the approved action
    from src.agent.executor import execute_agent

    resume_message = f"[Action approved: {approval.description}]"

    # Add the approval confirmation to the conversation first
    if agent.conversation_id:
        db.add_message(
            agent.conversation_id,
            MessageRole.USER,
            resume_message,
        )

    result, error_msg = execute_agent(agent, user, "manual", execution.id)

    if result is True:
        db.update_execution(execution.id, status="completed")
    elif result == "waiting_approval":
        # Agent needs another approval (shouldn't happen in normal flow)
        pass
    else:
        db.update_execution(execution.id, status="failed", error_message=error_msg)

    logger.info(
        "Approval processed and agent resumed",
        extra={
            "approval_id": approval_id,
            "agent_id": agent.id,
            "result": str(result),
        },
    )

    return {"status": "approved"}


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

    # Get the agent to find the conversation
    agent = db.get_agent(approval.agent_id, user.id)

    # Resolve the approval
    resolved = db.resolve_approval(approval_id, user.id, approved=False)
    if not resolved:
        raise_not_found_error("Approval request")

    # Add rejection message to the conversation
    if agent and agent.conversation_id:
        rejection_message = f"[Action rejected: {approval.description}]"
        db.add_message(
            agent.conversation_id,
            MessageRole.USER,
            rejection_message,
        )

    # Update any waiting_approval execution to failed
    executions = db.get_agent_executions(approval.agent_id, limit=1)
    if executions and executions[0].status == "waiting_approval":
        db.update_execution(
            executions[0].id,
            status="failed",
            error_message="Action rejected by user",
        )

    return {"status": "rejected"}
