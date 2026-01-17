"""Trigger agent tool for agent-to-agent communication.

This tool allows autonomous agents to trigger other agents to run,
enabling multi-agent workflows and coordination.
"""

from langchain_core.tools import tool

from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)


@tool
def trigger_agent(agent_name: str, message: str = "Continue") -> str:
    """Trigger another autonomous agent to run.

    Use this to delegate tasks to other agents or coordinate multi-agent workflows.
    The target agent must be enabled and owned by the same user.

    Args:
        agent_name: The name of the agent to trigger
        message: Optional message to pass to the triggered agent

    Returns:
        Status message indicating if the agent was triggered successfully
    """
    # Import here to avoid circular imports
    from src.agent.executor import (
        AgentBlockedError,
        AgentExecutor,
        get_agent_context,
        get_trigger_chain,
    )
    from src.agent.tools.request_approval import ApprovalRequestedException

    # Get current context to find user
    context = get_agent_context()
    if not context:
        return "Error: trigger_agent can only be used by autonomous agents"

    user_id = context.user.id

    # Find the target agent
    target = db.get_agent_by_name(user_id, agent_name)
    if not target:
        return f"Agent '{agent_name}' not found"

    if not target.enabled:
        return f"Agent '{agent_name}' is disabled"

    # Check for circular triggers
    chain = get_trigger_chain()
    if target.id in chain:
        return f"Cannot trigger '{agent_name}' - would create circular dependency"

    logger.info(
        "Triggering agent",
        extra={
            "source_agent": context.agent.name,
            "target_agent": agent_name,
            "message": message[:100],
        },
    )

    # Execute the target agent
    executor = AgentExecutor(
        agent=target,
        user=context.user,
        trigger_type="agent_trigger",
        triggered_by_agent_id=context.agent.id,
    )

    try:
        result = executor.run(message)
        return f"Agent '{agent_name}' completed successfully (status: {result.status})"
    except AgentBlockedError as e:
        return f"Agent '{agent_name}' is blocked: {e}"
    except ApprovalRequestedException:
        return f"Agent '{agent_name}' is waiting for user approval"
    except Exception as e:
        logger.error(
            "Failed to trigger agent",
            extra={"target_agent": agent_name, "error": str(e)},
        )
        return f"Agent '{agent_name}' failed: {str(e)}"
