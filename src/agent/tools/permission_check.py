"""Permission checking for autonomous agent tools.

This module provides functions to check if a tool is blocked for an agent
based on its configured tool permissions.

Note: The approval system is now LLM-driven. Agents decide when to call
the `request_approval` tool for sensitive actions. This module only handles
the BLOCKED case (tools not in the agent's permission list).
"""

from collections.abc import Callable
from functools import wraps
from typing import Any

from src.agent.permissions import (
    PermissionResult,
    check_tool_permission,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ToolBlockedError(Exception):
    """Raised when a tool is blocked due to permissions."""

    def __init__(self, tool_name: str, message: str = "Tool not permitted"):
        self.tool_name = tool_name
        super().__init__(f"{tool_name}: {message}")


class ApprovalRequiredError(Exception):
    """Raised when a destructive action runs without a consumed approval.

    The ToolNode converts this into a tool error the model can read; the
    expected reaction is a request_approval call, after which the user's
    approval authorizes exactly one destructive call (S9 hardening: the
    confirmation rule is enforced in code, not just in the prompt, so a
    prompt-injected agent cannot delete data without the user's click).
    """


# Destructive operations that require a consumed user approval when
# running in an agent context. Extend per tool as needed.
DESTRUCTIVE_OPERATIONS: dict[str, frozenset[str]] = {
    "todoist": frozenset({"delete_task", "delete_project", "delete_section"}),
    "google_calendar": frozenset({"delete_event"}),
}


def _check_destructive_approval(agent_id: str, tool_name: str, operation: str) -> None:
    """Require + consume an approved request for a destructive operation."""
    from src.db.models import db

    if db.consume_approved_request(agent_id, tool_name):
        logger.info(
            "Destructive action authorized by consumed approval",
            extra={"agent_id": agent_id, "tool_name": tool_name, "operation": operation},
        )
        return

    raise ApprovalRequiredError(
        f"'{operation}' is destructive and requires explicit user approval - this is "
        f"enforced, the action cannot run without it. Call request_approval with a "
        f'description of exactly what will be deleted and tool_name="{tool_name}", '
        f"then wait for the user's decision. Each approval authorizes one deletion; "
        f"for several deletions, request approval for each."
    )


def check_autonomous_permission(tool_name: str, tool_args: dict[str, Any]) -> None:
    """Check if a tool is allowed for the current autonomous agent.

    This function checks if the tool is in the agent's permitted tools list.
    If not, it raises ToolBlockedError.

    Args:
        tool_name: Name of the tool being called
        tool_args: Arguments passed to the tool (used for logging)

    Raises:
        ToolBlockedError: If the tool is blocked for this agent
    """
    # Lazy import to avoid circular dependency
    from src.agent.executor import get_agent_context

    # Get agent context - if not in autonomous mode, allow all
    context = get_agent_context()
    if context is None or context.agent is None:
        # Not running as autonomous agent, skip permission check
        return

    agent = context.agent

    # Check permission
    result = check_tool_permission(agent, tool_name, tool_args)

    if result == PermissionResult.BLOCKED:
        logger.warning(
            "Tool blocked for agent",
            extra={
                "agent_id": agent.id,
                "tool_name": tool_name,
                "operation": tool_args.get("operation"),
            },
        )
        raise ToolBlockedError(
            tool_name,
            f"This agent is not permitted to use {tool_name}. "
            "Update the agent's tool permissions if this is needed.",
        )

    # Destructive operations additionally require a consumed user approval
    operation = tool_args.get("operation")
    if operation in DESTRUCTIVE_OPERATIONS.get(tool_name, frozenset()):
        _check_destructive_approval(agent.id, tool_name, str(operation))


def requires_permission(tool_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that checks tool permissions for autonomous agents.

    Usage:
        @requires_permission("todoist")
        def todoist_tool(operation: str, ...):
            ...

    The decorator checks if the tool is allowed before executing.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Build tool_args from function arguments
            tool_args = dict(kwargs)

            # Check permission (raises ToolBlockedError if blocked)
            check_autonomous_permission(tool_name, tool_args)

            # Permission granted, execute the tool
            return func(*args, **kwargs)

        return wrapper

    return decorator
