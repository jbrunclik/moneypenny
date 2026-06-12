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
    "todoist": frozenset({"delete_task", "delete_project", "delete_section", "archive_project"}),
    "google_calendar": frozenset({"delete_event"}),
}

# Which tool argument identifies the entity a destructive operation acts
# on. Used for argument-level approval matching: an approval created
# with a target_id only authorizes the call whose entity matches it.
_OPERATION_TARGET_PARAM: dict[str, str] = {
    "delete_task": "task_id",
    "delete_project": "project_id",
    "delete_section": "section_id",
    "archive_project": "project_id",
    "delete_event": "event_id",
    "update_event": "event_id",
}

# update_event is gated only when it actually reschedules or changes
# attendees - routine edits (summary, description, reminders) stay free
_UPDATE_EVENT_GATED_FIELDS = ("start_time", "end_time", "attendees")


def _destructive_operation(tool_name: str, tool_args: dict[str, Any]) -> str | None:
    """The operation name when this call needs an approval, else None."""
    operation = tool_args.get("operation")
    if operation in DESTRUCTIVE_OPERATIONS.get(tool_name, frozenset()):
        return str(operation)
    if (
        tool_name == "google_calendar"
        and operation == "update_event"
        and any(tool_args.get(field) for field in _UPDATE_EVENT_GATED_FIELDS)
    ):
        return str(operation)
    return None


def _check_destructive_approval(
    agent_id: str, tool_name: str, operation: str, target_id: str | None
) -> None:
    """Require + consume an approved request for a destructive operation."""
    from src.db.models import db

    if db.consume_approved_request(agent_id, tool_name, target_id=target_id):
        logger.info(
            "Destructive action authorized by consumed approval",
            extra={
                "agent_id": agent_id,
                "tool_name": tool_name,
                "operation": operation,
                "target_id": target_id,
            },
        )
        return

    raise ApprovalRequiredError(
        f"'{operation}' is a destructive change and requires explicit user approval - "
        f"this is enforced, the action cannot run without it. Call request_approval "
        f"with a description of exactly what will change, "
        f'tool_name="{tool_name}", and target_id="{target_id or "<entity id>"}" '
        f"(the id of the item being changed), then wait for the user's decision. "
        f"Each approval authorizes one matching call; for several changes, request "
        f"approval for each."
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
    destructive_op = _destructive_operation(tool_name, tool_args)
    if destructive_op:
        target_param = _OPERATION_TARGET_PARAM.get(destructive_op)
        target_id = tool_args.get(target_param) if target_param else None
        _check_destructive_approval(
            agent.id, tool_name, destructive_op, str(target_id) if target_id else None
        )


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
