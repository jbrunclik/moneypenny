"""Trigger agent tool for agent-to-agent communication.

This tool allows autonomous agents to trigger other agents to run,
enabling multi-agent workflows and coordination.
"""

from langchain_core.tools import tool

from src.agent.tools.errors import tool_error
from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _refusal(agent_name: str, target_id: str | None, enabled: bool, chain: list[str]) -> str | None:
    """Why the target cannot be triggered, if it cannot."""
    if target_id is None:
        return f"Agent '{agent_name}' not found"
    if not enabled:
        return f"Agent '{agent_name}' is disabled"
    if target_id in chain:
        return f"Cannot trigger '{agent_name}' - would create circular dependency"
    # Bound distinct-agent chain depth (S5): the chain already contains every
    # agent above us (including this one), so its length IS the current depth
    if len(chain) >= Config.AGENT_MAX_TRIGGER_DEPTH:
        return (
            f"Cannot trigger '{agent_name}' - maximum trigger depth "
            f"({Config.AGENT_MAX_TRIGGER_DEPTH}) reached"
        )
    return None


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
    from src.agent.item_scheduler import (  # noqa: PLC0415 - cycle: item_scheduler -> item_runner -> tools
        JobBusyError,
        JobHeldError,
        run_job_now,
    )
    from src.agent.run_context import (  # noqa: PLC0415 - cycle: run_context -> tools -> trigger_agent
        get_job_context,
        get_trigger_chain,
    )

    # Get current context to find user
    context = get_job_context()
    if not context:
        return tool_error("trigger_agent can only be used by autonomous agents", retriable=False)

    user_id = context.user.id
    chain = get_trigger_chain()
    target = db.get_standing_chat_by_name(user_id, agent_name)
    refusal = _refusal(
        agent_name, target.id if target else None, bool(target and target.enabled), chain
    )
    if refusal or target is None:
        return refusal or f"Agent '{agent_name}' not found"

    logger.info(
        "Triggering agent",
        extra={
            "source_agent": context.name,
            "target_agent": agent_name,
            # NOT "message" - a reserved LogRecord key; logging raises
            # KeyError on it, killing the tool call before the executor ran
            "trigger_message": message[:100],
        },
    )

    # The target agent is a standing job (same id): run it with the chain so
    # far, so cycle and depth protection reach its own triggers
    job = target.job
    try:
        outcome = run_job_now(
            job, context.user, message=message, trigger="agent_trigger", trigger_chain=chain
        )
    except JobHeldError as held:
        return f"Agent '{agent_name}' did not run: it is {held}"
    except JobBusyError:
        return f"Agent '{agent_name}' is already running"
    except Exception as e:  # a tool must never raise into the graph
        logger.exception(
            "Failed to trigger agent",
            extra={"target_agent": agent_name, "error": str(e)},
        )
        return f"Agent '{agent_name}' failed: {e!s}"
    if outcome.status == "approval":
        return f"Agent '{agent_name}' is waiting for user approval"
    if outcome.status == "failed":
        return f"Agent '{agent_name}' failed: {outcome.error}"
    return f"Agent '{agent_name}' completed successfully (status: {outcome.status})"
