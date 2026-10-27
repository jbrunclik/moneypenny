"""Autonomous agents routes: CRUD and execution.

This module handles autonomous agents that run on cron schedules,
require approval for dangerous operations, and can trigger each other.
Sibling modules agent_command_center, agent_approvals and agent_assist attach
their routes to this module's blueprint (one "Agents" OpenAPI tag).
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

from apiflask import APIBlueprint
from croniter import croniter

from src.agent.executor import execute_agent
from src.api.errors import raise_not_found_error, raise_validation_error
from src.api.helpers.agent_responses import agent_to_response, execution_to_response
from src.api.rate_limiting import rate_limit_conversations
from src.api.schemas.agents import (
    AgentConversationSyncResponse,
    AgentExecutionsListResponse,
    AgentResponse,
    AgentsListResponse,
    CreateAgentRequest,
    TriggerAgentResponse,
    UpdateAgentRequest,
)
from src.api.schemas.common import StatusResponse
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.db.models import User, db
from src.utils.clock import to_api, utc_now
from src.utils.logging import get_logger

logger = get_logger(__name__)

api = APIBlueprint("agents", __name__, url_prefix="/api", tag="Agents")


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

    # Status and spending are batched (was 4 queries per agent - Q1)
    agents_status = db.list_agents_with_status(user.id)
    spending = db.get_agents_daily_spending(user.id)

    agents_response = [
        agent_to_response(
            item["agent"],
            item["unread_count"],
            item["has_pending_approval"],
            item["has_error"],
            item["last_execution_status"],
            daily_spending=spending.get(item["agent"].id, 0.0),
        )
        for item in agents_status
    ]

    return {"agents": agents_response}


@api.route("/agents", methods=["POST"])
@api.output(AgentResponse, status_code=201)
@api.doc(responses=[400, 401])
@rate_limit_conversations
@require_auth
@validate_request(CreateAgentRequest)
def create_agent(user: User, data: CreateAgentRequest) -> dict[str, Any]:
    """Create a new autonomous agent.

    Creates the agent and its dedicated conversation automatically.
    The conversation title will be "Agent: <name>".

    Returns the created agent with its conversation_id.
    """
    logger.info(
        "Creating agent",
        extra={"user_id": user.id, "agent_name": data.name},
    )

    # Validate cron expression if provided
    schedule = data.schedule
    if schedule:
        try:
            croniter(schedule)
        except ValueError:  # croniter's CroniterError is a ValueError
            raise_validation_error("Invalid cron expression")

    # Validate timezone if provided
    timezone = data.timezone
    try:
        ZoneInfo(timezone)
    except KeyError, ValueError, OSError:  # not found / malformed key / unreadable name
        raise_validation_error(f"Invalid timezone: {timezone}")

    # Check for duplicate name
    existing = db.get_agent_by_name(user.id, data.name)
    if existing:
        raise_validation_error(f"Agent with name '{data.name}' already exists")

    agent = db.create_agent(
        user_id=user.id,
        name=data.name,
        description=data.description,
        system_prompt=data.system_prompt,
        schedule=schedule,
        timezone=timezone,
        tool_permissions=data.tool_permissions,
        enabled=data.enabled,
        model=data.model,
        budget_limit=data.budget_limit,
        fresh_context=data.fresh_context,
    )

    logger.info("Agent created", extra={"agent_id": agent.id, "user_id": user.id})

    return agent_to_response(agent)


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

    return agent_to_response(agent, unread_count, has_pending, has_error, last_exec_status)


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

    agent = db.get_agent(agent_id, user.id)
    if not agent:
        raise_not_found_error("Agent")

    server_time = to_api(utc_now())

    if not agent.conversation_id:
        return {
            "conversation": None,
            "server_time": server_time,
        }

    # Get conversation with message count
    conv_data = db.get_conversation_with_message_count(agent.conversation_id)
    if not conv_data:
        return {
            "conversation": None,
            "server_time": server_time,
        }

    conv, message_count = conv_data

    return {
        "conversation": {
            "message_count": message_count,
            "updated_at": to_api(conv.updated_at),
        },
        "server_time": server_time,
    }


@api.route("/agents/<agent_id>", methods=["PATCH"])
@api.output(AgentResponse)
@api.doc(responses=[400, 401, 404])
@rate_limit_conversations
@require_auth
@validate_request(UpdateAgentRequest)
def update_agent(user: User, data: UpdateAgentRequest, agent_id: str) -> dict[str, Any]:
    """Update an agent's configuration.

    Only provided fields will be updated; others remain unchanged.
    If the name changes, the conversation title is updated to match.
    """
    logger.info(
        "Updating agent",
        extra={"user_id": user.id, "agent_id": agent_id},
    )

    # System-managed agents are defined by the app: prompt/tools/schedule
    # live in code and Settings. Only Settings (which calls the db layer
    # directly) may change them.
    existing_agent = db.get_agent(agent_id, user.id)
    if existing_agent and existing_agent.system_type:
        raise_validation_error("This built-in agent is managed from Settings and cannot be edited.")

    # Validate cron expression if provided
    schedule = data.schedule
    if schedule is not None and schedule != "":
        try:
            croniter(schedule)
        except ValueError:  # croniter's CroniterError is a ValueError
            raise_validation_error("Invalid cron expression")

    # Validate timezone if provided
    timezone = data.timezone
    if timezone:
        try:
            ZoneInfo(timezone)
        except KeyError, ValueError, OSError:  # not found / malformed key / unreadable name
            raise_validation_error(f"Invalid timezone: {timezone}")

    # Use model_dump(exclude_unset=True) to see which fields were actually in the JSON
    # This allows us to distinguish between a missing field and an explicit null
    provided_data = data.model_dump(exclude_unset=True)

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
        fresh_context=get_arg("fresh_context"),
    )

    if not agent:
        raise_not_found_error("Agent")

    has_pending = db.has_pending_approval(agent.id)
    unread_count = db.get_agent_unread_count(agent.id)
    last_exec_status = db.get_last_execution_status(agent.id)
    has_error = last_exec_status == "failed"

    return agent_to_response(agent, unread_count, has_pending, has_error, last_exec_status)


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

    # System-managed agents live and die with their Settings toggle
    existing_agent = db.get_agent(agent_id, user.id)
    if existing_agent and existing_agent.system_type:
        raise_validation_error(
            "This built-in agent cannot be deleted - disable it from Settings instead."
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
        "execution": execution_to_response(execution),
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
        "executions": [execution_to_response(e) for e in executions],
    }
