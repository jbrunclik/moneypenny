"""Permission checking for a job run's tool calls.

A run's permissions come from its job's grants (run_permissions): None means
all tools; a list names the tools it may use beyond ALWAYS_SAFE_TOOLS.

Note: The approval system is now LLM-driven. Agents decide when to call
the `request_approval` tool for sensitive actions (see request_approval.py).
This module only handles the BLOCKED case.
"""

from collections.abc import Mapping
from enum import Enum
from typing import Any

from src.utils.logging import get_logger

logger = get_logger(__name__)


class PermissionResult(Enum):
    """Result of a permission check."""

    ALLOWED = "allowed"
    BLOCKED = "blocked"


# Tools that are always safe and always allowed. kv_store is included because
# it is unconditionally bound for agents (auto and interactive) and only
# touches the agent's own per-user K/V namespace.
ALWAYS_SAFE_TOOLS: set[str] = {
    "web_search",
    "fetch_url",
    "research",  # read-only web: search + fetch composite
    "retrieve_file",
    "create_file",  # attaches generated content to the reply
    "load_skill",  # read-only: returns repo-authored instructions
    "request_approval",
    "edit_standing_chat",  # unattended it only files an approval request
    "kv_store",
    # Read-only places/routing lookups (Mapy.com)
    "search_places",
    "get_route",
    "list_places",
}


# Grant levels (standing chats phase 2): "<tool>" lets a run read there,
# "<tool>:write" also change things. A write without the write level is a
# draft the user approves (permission_check). WhatsApp only messages the user
# themselves, so it is a notification, not a write.
WRITE_SUFFIX = ":write"
ALL_TOOLS_GRANT = "*"
WRITE_LEVEL_TOOLS = frozenset({"todoist", "google_calendar", "garmin_workout", "rouvy_workout"})
_READ_PREFIXES = ("get", "list", "search")


def base_tool(grant: str) -> str:
    """The tool a grant names ("todoist:write" -> "todoist")."""
    return grant.removesuffix(WRITE_SUFFIX)


def is_write_call(tool_name: str, tool_args: Mapping[str, object]) -> bool:
    """A call that changes something in a writable integration."""
    if tool_name not in WRITE_LEVEL_TOOLS:
        return False
    operation = str(tool_args.get("operation") or tool_args.get("action") or "")
    return not operation.startswith(_READ_PREFIXES)


def run_permissions(grants: list[str] | None) -> list[str] | None:
    """A run's permissions from its job's grants: None (unrestricted) for all
    tools, [] for a light item (no grants), else the grants."""
    if grants is None:
        return []
    return None if ALL_TOOLS_GRANT in grants else list(grants)


def has_write_grant(permissions: list[str] | None, tool_name: str) -> bool:
    """All tools (no list) or the tool's write level."""
    return permissions is None or f"{tool_name}{WRITE_SUFFIX}" in permissions


def check_tool_permission(
    permissions: list[str] | None,
    tool_name: str,
    tool_args: dict[str, Any],
) -> PermissionResult:
    """Check if a tool call is allowed for a job's run.

    Args:
        permissions: The run's permissions (run_permissions)
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
    if permissions is not None and tool_name not in {base_tool(g) for g in permissions}:
        logger.info("Tool blocked - not in the job's grants", extra={"tool": tool_name})
        return PermissionResult.BLOCKED

    # 3. Default: allow (for tools like trigger_agent, generate_image, etc.)
    return PermissionResult.ALLOWED
