"""Permission checking for autonomous agent tool calls.

This module checks whether an agent is allowed to use a specific tool
based on its configured tool_permissions list.

Note: The approval system is now LLM-driven. Agents decide when to call
the `request_approval` tool for sensitive actions (see request_approval.py).
This module only handles the BLOCKED case.
"""

from enum import Enum
from typing import Any

from src.db.models.dataclasses import Agent
from src.utils.logging import get_logger

logger = get_logger(__name__)


class PermissionResult(Enum):
    """Result of a permission check."""

    ALLOWED = "allowed"
    BLOCKED = "blocked"


# Tools that are always safe (read-only operations) and always allowed
ALWAYS_SAFE_TOOLS: set[str] = {"web_search", "fetch_url", "retrieve_file", "request_approval"}


def check_tool_permission(
    agent: Agent,
    tool_name: str,
    tool_args: dict[str, Any],
) -> PermissionResult:
    """Check if a tool call is allowed for an autonomous agent.

    Args:
        agent: The agent making the tool call
        tool_name: Name of the tool being called
        tool_args: Arguments to the tool (used for logging)

    Returns:
        PermissionResult indicating whether the call is allowed or blocked
    """
    # 1. Always-safe tools can always proceed
    if tool_name in ALWAYS_SAFE_TOOLS:
        return PermissionResult.ALLOWED

    # 2. Check if tool is in agent's allowed list
    # If permissions list exists (even if empty), only those tools are allowed
    if agent.tool_permissions is not None:
        if tool_name not in agent.tool_permissions:
            logger.info(
                "Tool blocked - not in agent's permissions",
                extra={"agent_id": agent.id, "tool": tool_name},
            )
            return PermissionResult.BLOCKED

    # 3. Default: allow (for tools like trigger_agent, generate_image, etc.)
    return PermissionResult.ALLOWED


def get_safe_tools() -> list[str]:
    """Get list of always-safe tool names."""
    return list(ALWAYS_SAFE_TOOLS)
