"""Permission checking for autonomous agent tools.

This module provides functions to check if a tool is blocked for an agent
based on its configured tool permissions.

A tool outside the job's grants is BLOCKED. A destructive operation, or a
write without the write level, needs the user's yes to exactly that call:
the gate files the call's card and pauses the run (src/agent/run_approvals.py).
In a chat turn a destructive operation waits on the turn's card instead
(src/agent/chat_changes.py).
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from src.agent.permissions import (
    PermissionResult,
    check_tool_permission,
    has_write_grant,
    is_write_call,
)
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

logger = get_logger(__name__)


class ToolBlockedError(Exception):
    """Raised when a tool is blocked due to permissions."""

    def __init__(self, tool_name: str, message: str = "Tool not permitted"):
        self.tool_name = tool_name
        super().__init__(f"{tool_name}: {message}")


# Destructive operations that require a consumed user approval when
# running in an agent context. Extend per tool as needed.
DESTRUCTIVE_OPERATIONS: dict[str, frozenset[str]] = {
    "todoist": frozenset({"delete_task", "delete_project", "delete_section", "archive_project"}),
    "google_calendar": frozenset({"delete_event"}),
    "rouvy_workout": frozenset({"delete"}),
}

# update_event is gated only when it actually reschedules or changes
# attendees - routine edits (summary, description, reminders) stay free
_UPDATE_EVENT_GATED_FIELDS = ("start_time", "end_time", "attendees")


def _destructive_operation(tool_name: str, tool_args: dict[str, Any]) -> str | None:
    """The operation name when this call needs an approval, else None."""
    operation = tool_args.get("operation") or tool_args.get("action")
    if operation in DESTRUCTIVE_OPERATIONS.get(tool_name, frozenset()):
        return str(operation)
    if (
        tool_name == "google_calendar"
        and operation == "update_event"
        and any(tool_args.get(field) for field in _UPDATE_EVENT_GATED_FIELDS)
    ):
        return str(operation)
    return None


def call_arguments(tool: BaseTool, scope: Mapping[str, object]) -> dict[str, object]:
    """A tool call's arguments, as the gate sees them: every parameter of
    the tool given a value (None = not given). The card shows - and the
    approval binds - exactly these, so pass locals() at the call."""
    return {name: scope[name] for name in tool.args if scope.get(name) is not None}


def check_autonomous_permission(tool_name: str, tool_args: dict[str, Any]) -> str | None:
    """Check if a tool is allowed for the current autonomous agent - or, in a
    chat turn, hold a delete or archive on the turn's card.

    Returns the card text the tool answers with instead of acting (chat), or
    None to go ahead.

    This function checks if the tool is in the agent's permitted tools list.
    If not, it raises ToolBlockedError.

    Args:
        tool_name: Name of the tool being called
        tool_args: Arguments passed to the tool (used for logging)

    Raises:
        ToolBlockedError: If the tool is blocked for this agent
    """
    from src.agent.run_context import get_job_context  # noqa: PLC0415 - cycle: run_context -> tools -> browser -> permission_check

    # A chat turn: every bound tool is allowed, but a delete or archive
    # waits on the turn's card (src/agent/chat_changes.py)
    context = get_job_context()
    if context is None:
        from src.agent.chat_changes import hold_destructive_call  # noqa: PLC0415 - cycle: chat_changes imports the tools

        return hold_destructive_call(tool_name, tool_args)
    job_id = context.item.id
    permissions = context.permissions
    result = check_tool_permission(permissions, tool_name, tool_args)

    if result == PermissionResult.BLOCKED:
        logger.warning(
            "Tool blocked for job",
            extra={
                "job_id": job_id,
                "tool_name": tool_name,
                "operation": tool_args.get("operation"),
            },
        )
        raise ToolBlockedError(
            tool_name,
            f"This agent is not permitted to use {tool_name}. "
            "Update the agent's tool permissions if this is needed.",
        )

    from src.agent.run_approvals import require_call_approval  # noqa: PLC0415 - cycle: run_approvals imports the tools

    # A destructive operation needs the user's yes to exactly this call, even
    # with the write level; a write without the level is a draft (one yes per
    # call). Without it the gate files the call's card and the run pauses.
    if _destructive_operation(tool_name, tool_args):
        require_call_approval(context, tool_name, tool_args, destructive=True)
    elif is_write_call(tool_name, tool_args) and not has_write_grant(permissions, tool_name):
        require_call_approval(context, tool_name, tool_args, destructive=False)
    return None
