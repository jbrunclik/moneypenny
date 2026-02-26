"""Autonomous agents routes: CRUD, command center, approvals.

This module handles autonomous agents that run on cron schedules,
require approval for dangerous operations, and can trigger each other.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

from apiflask import APIBlueprint

from src.agent.content import extract_text_content
from src.agent.tools.google_calendar import is_google_calendar_available
from src.agent.tools.todoist import is_todoist_available
from src.agent.tools.whatsapp import is_whatsapp_available
from src.api.errors import raise_not_found_error, raise_validation_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.schemas import (
    AgentConversationSyncResponse,
    AgentExecutionsListResponse,
    AgentResponse,
    AgentsListResponse,
    CommandCenterResponse,
    CreateAgentRequest,
    EnhancePromptRequest,
    EnhancePromptResponse,
    MessageRole,
    ParseScheduleRequest,
    ParseScheduleResponse,
    PendingApprovalsResponse,
    StatusResponse,
    TriggerAgentResponse,
    UpdateAgentRequest,
)
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import Agent, AgentExecution, ApprovalRequest, User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)

api = APIBlueprint("agents", __name__, url_prefix="/api", tag="Agents")


# ============================================================================
# Helper Functions
# ============================================================================


def _agent_to_response(
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
        "last_run_at": agent.last_run_at.isoformat() if agent.last_run_at else None,
        "next_run_at": agent.next_run_at.isoformat() if agent.next_run_at else None,
        "created_at": agent.created_at.isoformat(),
        "updated_at": agent.updated_at.isoformat(),
        "budget_limit": agent.budget_limit,
        "daily_spending": daily_spending,
        "has_pending_approval": has_pending_approval,
        "has_error": has_error,
        "unread_count": unread_count,
        "last_execution_status": last_execution_status,
    }


def _execution_to_response(execution: AgentExecution) -> dict[str, Any]:
    """Convert an AgentExecution object to response dict."""
    return {
        "id": execution.id,
        "agent_id": execution.agent_id,
        "status": execution.status,
        "trigger_type": execution.trigger_type,
        "triggered_by_agent_id": execution.triggered_by_agent_id,
        "started_at": execution.started_at.isoformat(),
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
        "error_message": execution.error_message,
    }


def _approval_to_response(approval: ApprovalRequest, agent_name: str) -> dict[str, Any]:
    """Convert an ApprovalRequest object to response dict."""
    return {
        "id": approval.id,
        "agent_id": approval.agent_id,
        "agent_name": agent_name,
        "tool_name": approval.tool_name,
        "tool_args": approval.tool_args,
        "description": approval.description,
        "status": approval.status,
        "created_at": approval.created_at.isoformat(),
        "resolved_at": approval.resolved_at.isoformat() if approval.resolved_at else None,
    }


# ============================================================================
# Agent CRUD Routes
# ============================================================================


@api.route("/agents", methods=["GET"])
@api.output(AgentsListResponse)
@api.doc(responses=[401])
@require_auth
def list_agents(user: User) -> dict[str, Any]:
    """List all autonomous agents for the current user.

    Returns agents ordered by creation date (newest first).
    Each agent includes unread_count and has_pending_approval flags.
    """
    logger.debug("Listing agents", extra={"user_id": user.id})

    agents = db.list_agents(user.id)

    # Get status info for each agent
    agents_response = []
    for agent in agents:
        has_pending = db.has_pending_approval(agent.id)
        unread_count = db.get_agent_unread_count(agent.id)
        last_exec_status = db.get_last_execution_status(agent.id)
        has_error = last_exec_status == "failed"
        agents_response.append(
            _agent_to_response(agent, unread_count, has_pending, has_error, last_exec_status)
        )

    return {"agents": agents_response}


@api.route("/agents", methods=["POST"])
@api.input(CreateAgentRequest)
@api.output(AgentResponse, status_code=201)
@api.doc(responses=[400, 401])
@rate_limit_conversations
@require_auth
def create_agent(user: User, json_data: CreateAgentRequest) -> dict[str, Any]:
    """Create a new autonomous agent.

    Creates the agent and its dedicated conversation automatically.
    The conversation title will be "Agent: <name>".

    Returns the created agent with its conversation_id.
    """
    logger.info(
        "Creating agent",
        extra={"user_id": user.id, "agent_name": json_data.name},
    )

    # Validate cron expression if provided
    schedule = json_data.schedule
    if schedule:
        try:
            from croniter import croniter

            croniter(schedule)
        except Exception:
            raise_validation_error("Invalid cron expression")

    # Validate timezone if provided
    timezone = json_data.timezone
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(timezone)
    except Exception:
        raise_validation_error(f"Invalid timezone: {timezone}")

    # Check for duplicate name
    existing = db.get_agent_by_name(user.id, json_data.name)
    if existing:
        raise_validation_error(f"Agent with name '{json_data.name}' already exists")

    agent = db.create_agent(
        user_id=user.id,
        name=json_data.name,
        description=json_data.description,
        system_prompt=json_data.system_prompt,
        schedule=schedule,
        timezone=timezone,
        tool_permissions=json_data.tool_permissions,
        enabled=json_data.enabled,
        model=json_data.model,
        budget_limit=json_data.budget_limit,
    )

    logger.info("Agent created", extra={"agent_id": agent.id, "user_id": user.id})

    return _agent_to_response(agent)


@api.route("/agents/<agent_id>", methods=["GET"])
@api.output(AgentResponse)
@api.doc(responses=[401, 404])
@require_auth
def get_agent(user: User, agent_id: str) -> dict[str, Any]:
    """Get a specific agent by ID.

    Returns the agent with unread_count and has_pending_approval flags.
    """
    agent = db.get_agent(agent_id, user.id)
    if not agent:
        raise_not_found_error("Agent")

    has_pending = db.has_pending_approval(agent.id)
    unread_count = db.get_agent_unread_count(agent.id)
    last_exec_status = db.get_last_execution_status(agent.id)
    has_error = last_exec_status == "failed"

    return _agent_to_response(agent, unread_count, has_pending, has_error, last_exec_status)


@api.route("/agents/<agent_id>/conversation/sync", methods=["GET"])
@api.output(AgentConversationSyncResponse)
@api.doc(responses=[401, 404])
@require_auth
def sync_agent_conversation(user: User, agent_id: str) -> dict[str, Any]:
    """Sync agent conversation - returns message count and updated_at.

    Used for real-time synchronization when viewing an agent's conversation.
    This allows detection of external updates to the agent conversation.

    Returns:
    - conversation: Object with message_count and updated_at, or null if no conversation
    - server_time: Current server timestamp to use for next sync
    """
    from datetime import datetime

    agent = db.get_agent(agent_id, user.id)
    if not agent:
        raise_not_found_error("Agent")

    server_time = datetime.now(UTC)

    if not agent.conversation_id:
        return {
            "conversation": None,
            "server_time": server_time.isoformat(),
        }

    # Get conversation with message count
    conv_data = db.get_conversation_with_message_count(agent.conversation_id)
    if not conv_data:
        return {
            "conversation": None,
            "server_time": server_time.isoformat(),
        }

    conv, message_count = conv_data

    return {
        "conversation": {
            "message_count": message_count,
            "updated_at": conv.updated_at.isoformat(),
        },
        "server_time": server_time.isoformat(),
    }


@api.route("/agents/<agent_id>", methods=["PATCH"])
@api.input(UpdateAgentRequest)
@api.output(AgentResponse)
@api.doc(responses=[400, 401, 404])
@rate_limit_conversations
@require_auth
def update_agent(user: User, agent_id: str, json_data: UpdateAgentRequest) -> dict[str, Any]:
    """Update an agent's configuration.

    Only provided fields will be updated; others remain unchanged.
    If the name changes, the conversation title is updated to match.
    """
    logger.info(
        "Updating agent",
        extra={"user_id": user.id, "agent_id": agent_id},
    )

    # Validate cron expression if provided
    schedule = json_data.schedule
    if schedule is not None and schedule != "":
        try:
            from croniter import croniter

            croniter(schedule)
        except Exception:
            raise_validation_error("Invalid cron expression")

    # Validate timezone if provided
    timezone = json_data.timezone
    if timezone:
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(timezone)
        except Exception:
            raise_validation_error(f"Invalid timezone: {timezone}")

    # Use model_dump(exclude_unset=True) to see which fields were actually in the JSON
    # This allows us to distinguish between a missing field and an explicit null
    provided_data = json_data.model_dump(exclude_unset=True)

    def get_arg(field_name: str) -> Any:
        return provided_data.get(field_name, ...)

    agent = db.update_agent(
        agent_id=agent_id,
        user_id=user.id,
        name=get_arg("name"),
        description=get_arg("description"),
        system_prompt=get_arg("system_prompt"),
        schedule=get_arg("schedule"),
        timezone=get_arg("timezone"),
        tool_permissions=get_arg("tool_permissions"),
        enabled=get_arg("enabled"),
        model=get_arg("model"),
        budget_limit=get_arg("budget_limit"),
    )

    if not agent:
        raise_not_found_error("Agent")

    has_pending = db.has_pending_approval(agent.id)
    unread_count = db.get_agent_unread_count(agent.id)
    last_exec_status = db.get_last_execution_status(agent.id)
    has_error = last_exec_status == "failed"

    return _agent_to_response(agent, unread_count, has_pending, has_error, last_exec_status)


@api.route("/agents/<agent_id>", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[401, 404])
@rate_limit_conversations
@require_auth
def delete_agent(user: User, agent_id: str) -> dict[str, Any]:
    """Delete an agent and its dedicated conversation.

    Also deletes:
    - All messages in the agent's conversation
    - All approval requests for this agent
    - All execution records for this agent

    Message costs are preserved for accurate cost tracking.
    """
    logger.info(
        "Deleting agent",
        extra={"user_id": user.id, "agent_id": agent_id},
    )

    deleted = db.delete_agent(agent_id, user.id)
    if not deleted:
        raise_not_found_error("Agent")

    return {"status": "deleted"}


@api.route("/agents/<agent_id>/mark-viewed", methods=["POST"])
@api.output(StatusResponse)
@api.doc(responses=[401, 404])
@require_auth
def mark_agent_viewed(user: User, agent_id: str) -> dict[str, Any]:
    """Mark an agent's conversation as viewed.

    Updates the last_viewed_at timestamp to reset unread count.
    Should be called when user opens the agent's conversation.
    """
    updated = db.update_agent_last_viewed(agent_id, user.id)
    if not updated:
        raise_not_found_error("Agent")

    return {"status": "viewed"}


# ============================================================================
# Agent Execution Routes
# ============================================================================


@api.route("/agents/<agent_id>/run", methods=["POST"])
@api.output(TriggerAgentResponse)
@api.doc(responses=[400, 401, 404])
@rate_limit_conversations
@require_auth
def trigger_agent(user: User, agent_id: str) -> dict[str, Any]:
    """Manually trigger an agent to run.

    Creates an execution record and runs the agent.
    If the agent is disabled or waiting for approval, returns an error.

    Returns the execution record with status.
    """
    from src.agent.executor import execute_agent

    logger.info(
        "Manually triggering agent",
        extra={"user_id": user.id, "agent_id": agent_id},
    )

    agent = db.get_agent(agent_id, user.id)
    if not agent:
        raise_not_found_error("Agent")

    # Check if agent is enabled
    if not agent.enabled:
        raise_validation_error("Agent is disabled")

    # Check if agent is blocked waiting for approval
    if db.has_pending_approval(agent.id):
        raise_validation_error("Agent is waiting for approval")

    # Check if agent is already running (prevent overlapping executions)
    if db.has_running_execution(agent.id):
        raise_validation_error("Agent is already running")

    # Check if agent is in cooldown period (prevent spamming)
    if db.is_in_cooldown(agent.id):
        raise_validation_error("Agent was recently executed. Please wait a few seconds.")

    # Create execution record
    execution = db.create_execution(
        agent_id=agent.id,
        trigger_type="manual",
    )

    # Execute the agent
    result, error_message = execute_agent(agent, user, "manual", execution.id)

    if result is True:
        db.update_execution(execution.id, status="completed")
        message = "Agent executed successfully"
    elif result == "waiting_approval":
        # Don't override status - executor already set it to waiting_approval
        message = "Agent is waiting for approval"
    else:
        db.update_execution(execution.id, status="failed", error_message=error_message)
        message = f"Agent execution failed: {error_message}"

    # Refresh execution to get updated status
    executions = db.get_agent_executions(agent.id, limit=1)
    if executions:
        execution = executions[0]

    return {
        "execution": _execution_to_response(execution),
        "message": message,
    }


@api.route("/agents/<agent_id>/executions", methods=["GET"])
@api.output(AgentExecutionsListResponse)
@api.doc(responses=[401, 404])
@require_auth
def get_agent_executions(user: User, agent_id: str) -> dict[str, Any]:
    """Get execution history for an agent.

    Returns the 20 most recent executions, newest first.
    """
    agent = db.get_agent(agent_id, user.id)
    if not agent:
        raise_not_found_error("Agent")

    executions = db.get_agent_executions(agent.id, limit=20)

    return {
        "executions": [_execution_to_response(e) for e in executions],
    }


# ============================================================================
# Command Center Routes
# ============================================================================


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
            _agent_to_response(
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
            _approval_to_response(
                approval_data["approval"],
                approval_data["agent_name"],
            )
        )

    executions_response = [_execution_to_response(e) for e in data["recent_executions"]]

    return {
        "agents": agents_response,
        "pending_approvals": approvals_response,
        "recent_executions": executions_response,
        "total_unread": data["total_unread"],
        "agents_waiting": data["agents_waiting"],
        "agents_with_errors": data["agents_with_errors"],
    }


# ============================================================================
# Approval Routes
# ============================================================================


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
        approvals_response.append(_approval_to_response(approval, agent_name))

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


# ============================================================================
# Development/Testing Routes
# ============================================================================


@api.route("/agents/dev/evaluate-schedules", methods=["POST"])
@api.output(StatusResponse)
@api.doc(responses=[400, 401])
@require_auth
def evaluate_schedules(user: User) -> dict[str, Any]:
    """(Dev only) Evaluate and run scheduled agents.

    This endpoint is for local development/testing without systemd timers.
    It evaluates which agents are due to run based on their cron schedules
    and triggers them.

    Only available in development mode (FLASK_ENV=development).
    """
    from src.config import Config

    if not Config.is_development():
        raise_validation_error("This endpoint is only available in development mode")

    from datetime import datetime

    from croniter import croniter

    logger.info(
        "Evaluating scheduled agents (dev mode)",
        extra={"user_id": user.id},
    )

    agents = db.list_agents(user.id)
    triggered_count = 0
    skipped_count = 0

    now = datetime.now(UTC)

    for agent in agents:
        # Skip disabled agents
        if not agent.enabled:
            logger.debug(
                f"Agent {agent.name} is disabled, skipping",
                extra={"agent_id": agent.id},
            )
            skipped_count += 1
            continue

        # Skip agents without a schedule (manual only)
        if not agent.schedule:
            logger.debug(
                f"Agent {agent.name} has no schedule (manual only), skipping",
                extra={"agent_id": agent.id},
            )
            skipped_count += 1
            continue

        # Skip agents waiting for approval
        if db.has_pending_approval(agent.id):
            logger.debug(
                f"Agent {agent.name} is waiting for approval, skipping",
                extra={"agent_id": agent.id},
            )
            skipped_count += 1
            continue

        # Check if agent is due to run
        # Use agent's timezone for evaluation
        try:
            from zoneinfo import ZoneInfo

            agent_tz = ZoneInfo(agent.timezone)
            now_in_tz = now.astimezone(agent_tz)

            # Create croniter for the agent's schedule
            cron = croniter(agent.schedule, now_in_tz)

            # If next_run_at is set and it's in the past, agent should run
            if agent.next_run_at and agent.next_run_at <= now:
                logger.info(
                    f"Agent {agent.name} is due to run (next_run_at={agent.next_run_at})",
                    extra={"agent_id": agent.id},
                )

                # Create execution record
                execution = db.create_execution(
                    agent_id=agent.id,
                    trigger_type="scheduled",
                )

                # Get the user for this agent to execute with proper context
                agent_user = db.get_user_by_id(agent.user_id)
                if agent_user:
                    # Execute the agent
                    from src.agent.executor import execute_agent

                    result, error_msg = execute_agent(agent, agent_user, "scheduled", execution.id)
                    if result is True:
                        db.update_execution(execution.id, status="completed")
                    elif result == "waiting_approval":
                        # Don't override status - executor already set it to waiting_approval
                        pass
                    else:
                        db.update_execution(execution.id, status="failed", error_message=error_msg)
                else:
                    db.update_execution(
                        execution.id, status="failed", error_message="User not found"
                    )

                # Update next_run_at
                next_run = cron.get_next(datetime)
                db.update_agent_next_run(agent.id, next_run)

                triggered_count += 1
            else:
                # Not due yet
                next_run = cron.get_next(datetime)
                logger.debug(
                    f"Agent {agent.name} not due yet (next={next_run})",
                    extra={"agent_id": agent.id},
                )
                skipped_count += 1

        except Exception as e:
            logger.warning(
                f"Failed to evaluate schedule for agent {agent.name}: {e}",
                extra={"agent_id": agent.id},
            )
            skipped_count += 1

    return {
        "status": f"Triggered {triggered_count} agents, skipped {skipped_count}",
    }


# ============================================================================
# AI Assist Routes
# ============================================================================


_PROMPT_TOOL_DESCRIPTIONS: dict[str, str] = {
    "web_search": "Search the open web for current information, news, stats, and references.",
    "fetch_url": "Download the raw content of a specific URL (articles, docs, JSON) for analysis.",
    "retrieve_file": "Read files that the user previously uploaded in this conversation.",
    "generate_image": "Create or edit images through Gemini based on detailed prompts or references.",
    "execute_code": "Run short Python code in an isolated sandbox for data wrangling or calculations.",
    "request_approval": "Pause execution and ask the user for approval before sensitive work.",
    "trigger_agent": "Trigger another autonomous agent and optionally pass along instructions.",
    "todoist": "Create, update, and organize Todoist tasks, sections, and projects.",
    "google_calendar": "Read or modify Google Calendar events, attendees, and reminders.",
    "whatsapp": "Send WhatsApp notifications to the user with concise summaries and links.",
    "kv_store": "Persist and retrieve key-value data across conversations and executions.",
}

_PROMPT_BASE_TOOL_ORDER = [
    "web_search",
    "fetch_url",
    "retrieve_file",
    "generate_image",
    "execute_code",
    "request_approval",
    "trigger_agent",
]


def _is_todoist_connected_for_user(user: User) -> bool:
    """Return True if Todoist is configured at app level AND connected for this user."""
    return bool(is_todoist_available() and user.todoist_access_token)


def _is_calendar_connected_for_user(user: User) -> bool:
    """Return True if Google Calendar is configured at app level AND connected for this user."""
    return bool(is_google_calendar_available() and user.google_calendar_access_token)


def _is_whatsapp_enabled_for_user(user: User) -> bool:
    """Return True if WhatsApp is configured at app level AND user has set their phone."""
    return bool(is_whatsapp_available() and user.whatsapp_phone)


def _resolve_requested_tools(user: User, tool_permissions: list[str] | None) -> list[str]:
    """Resolve optional tools based on explicit permissions or available integrations.

    When tool_permissions is None, auto-detect based on user's actual connections.
    When tool_permissions is provided, return them (filtering will happen in maybe_add).
    """
    if tool_permissions is None:
        # Auto-detect based on user's actual connections (not just app config)
        tools: list[str] = []
        if _is_todoist_connected_for_user(user):
            tools.append("todoist")
        if _is_calendar_connected_for_user(user):
            tools.append("google_calendar")
        if _is_whatsapp_enabled_for_user(user):
            tools.append("whatsapp")
        return tools

    # Filter duplicates while preserving order
    seen: set[str] = set()
    filtered: list[str] = []
    for tool in tool_permissions:
        if tool not in seen:
            filtered.append(tool)
            seen.add(tool)
    return filtered


def _format_tool_prompt_section(user: User, tool_permissions: list[str] | None) -> str:
    """Build a bullet list describing the tools available to the agent.

    Only includes tools that are:
    1. Available at app level (config/env vars set)
    2. Connected for this specific user (for integration tools)
    """
    added: set[str] = set()
    lines: list[str] = []

    def maybe_add(tool_name: str) -> None:
        if tool_name in added:
            return
        description = _PROMPT_TOOL_DESCRIPTIONS.get(tool_name)
        if not description:
            return

        # Respect runtime availability (app-level config)
        if tool_name == "execute_code" and not Config.CODE_SANDBOX_ENABLED:
            return
        if tool_name == "generate_image" and not Config.GEMINI_API_KEY:
            return

        # Check user-level connections for integration tools
        if tool_name == "todoist" and not _is_todoist_connected_for_user(user):
            return
        if tool_name == "google_calendar" and not _is_calendar_connected_for_user(user):
            return
        if tool_name == "whatsapp" and not _is_whatsapp_enabled_for_user(user):
            return

        lines.append(f"- {tool_name}: {description}")
        added.add(tool_name)

    for base_tool in _PROMPT_BASE_TOOL_ORDER:
        maybe_add(base_tool)

    for tool in _resolve_requested_tools(user, tool_permissions):
        maybe_add(tool)

    # Include any additional tools from the request that are not in the preferred order
    if tool_permissions:
        for tool in tool_permissions:
            maybe_add(tool)

    return "\n".join(lines)


@api.route("/ai-assist/parse-schedule", methods=["POST"])
@api.input(ParseScheduleRequest)
@api.output(ParseScheduleResponse)
@api.doc(responses=[400, 401])
@rate_limit_conversations
@require_auth
def parse_schedule(user: User, json_data: ParseScheduleRequest) -> dict[str, Any]:
    """Parse natural language schedule description into cron expression.

    Uses an LLM to convert user-friendly schedule descriptions
    (e.g., "every weekday at 9am") into standard cron expressions.
    """
    import json
    import re

    from langchain_core.messages import HumanMessage
    from langchain_google_genai import ChatGoogleGenerativeAI

    logger.info(
        "Parsing schedule",
        extra={"user_id": user.id, "input": json_data.natural_language[:100]},
    )

    try:
        # Use direct LLM call without system prompt overhead
        # This is a simple task that doesn't need tools or memory
        model = ChatGoogleGenerativeAI(
            model=Config.DEFAULT_MODEL,
            google_api_key=Config.GEMINI_API_KEY,
            temperature=0.1,  # Low temperature for consistent parsing
        )

        prompt = f"""Convert this natural language schedule description to a cron expression.

Schedule: "{json_data.natural_language}"
Timezone context: {json_data.timezone}

Respond with ONLY a JSON object in this exact format:
{{"cron": "<5-part cron expression>", "explanation": "<human readable description>"}}

For example:
- "every day at 9am" -> {{"cron": "0 9 * * *", "explanation": "Every day at 9:00 AM"}}
- "weekdays at 8:30am" -> {{"cron": "30 8 * * 1-5", "explanation": "Monday through Friday at 8:30 AM"}}
- "first monday of month at noon" -> {{"cron": "0 12 1-7 * 1", "explanation": "First Monday of each month at 12:00 PM"}}

Use standard 5-part cron format: minute hour day-of-month month day-of-week"""

        response = model.invoke([HumanMessage(content=prompt)])
        response_text = extract_text_content(response.content)

        # Extract JSON from response (handle potential markdown code blocks)
        json_match = re.search(r"\{[^{}]*\}", response_text)
        if json_match:
            result = json.loads(json_match.group())
            cron = result.get("cron")
            explanation = result.get("explanation")

            # Validate the cron expression
            if cron:
                from croniter import croniter

                try:
                    croniter(cron)
                    return {"cron": cron, "explanation": explanation, "error": None}
                except Exception:
                    return {
                        "cron": None,
                        "explanation": None,
                        "error": "Generated invalid cron expression",
                    }

        return {"cron": None, "explanation": None, "error": "Could not parse schedule"}

    except Exception as e:
        logger.warning(f"Schedule parsing failed: {e}", exc_info=True)
        return {"cron": None, "explanation": None, "error": str(e)}


@api.route("/ai-assist/enhance-prompt", methods=["POST"])
@api.input(EnhancePromptRequest)
@api.output(EnhancePromptResponse)
@api.doc(responses=[400, 401])
@rate_limit_conversations
@require_auth
def enhance_prompt(user: User, json_data: EnhancePromptRequest) -> dict[str, Any]:
    """Enhance an agent's system prompt using AI.

    Takes the current prompt and agent context, then suggests
    improvements for clarity, completeness, and effectiveness.
    """
    from langchain_core.messages import HumanMessage
    from langchain_google_genai import ChatGoogleGenerativeAI

    logger.info(
        "Enhancing prompt",
        extra={"user_id": user.id, "agent_name": json_data.agent_name},
    )

    try:
        import json

        # Use direct LLM call without system prompt overhead
        # This is a simple task that doesn't need tools or memory
        model = ChatGoogleGenerativeAI(
            model=Config.DEFAULT_MODEL,
            google_api_key=Config.GEMINI_API_KEY,
            temperature=0.7,  # Moderate temperature for creative improvement
        )

        tool_section = _format_tool_prompt_section(user, json_data.tool_permissions)
        tool_section_text = (
            f"\nTools available to this agent:\n{tool_section}\n\nInclude guidance on how the agent should use these tools when relevant.\n"
            if tool_section
            else ""
        )

        prompt = f"""Improve this autonomous agent's system prompt to be clearer and more effective.

Agent name: {json_data.agent_name}

Current prompt:
---
{json_data.prompt}
---
{tool_section_text}
Provide an enhanced version that:
1. Has clear, actionable goals
2. Specifies any constraints or limitations
3. Defines success criteria where appropriate
4. Uses concise, direct language
5. Reflects how the agent should leverage the tools listed above when applicable

Respond with ONLY a JSON object in this exact format:
{{"enhanced_prompt": "<the improved prompt text>", "error": null}}

If the prompt cannot be improved (too vague, empty, or inappropriate), return:
{{"enhanced_prompt": null, "error": "<explanation of the issue>"}}"""

        response = model.invoke([HumanMessage(content=prompt)])
        response_text = extract_text_content(response.content)

        # Clean up response - remove markdown code blocks if present
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # Parse JSON response
        try:
            result = json.loads(text)
            enhanced = result.get("enhanced_prompt")
            error = result.get("error")

            if error:
                return {"enhanced_prompt": None, "error": error}
            if enhanced:
                return {"enhanced_prompt": enhanced, "error": None}
        except json.JSONDecodeError:
            # If JSON parsing fails, the response might be plain text
            # Use it as the enhanced prompt
            if text and not text.startswith("{"):
                return {"enhanced_prompt": text, "error": None}

        return {"enhanced_prompt": None, "error": "Could not enhance prompt"}

    except Exception as e:
        logger.warning(f"Prompt enhancement failed: {e}", exc_info=True)
        return {"enhanced_prompt": None, "error": str(e)}
