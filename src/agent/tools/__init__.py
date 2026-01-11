"""Agent tools package.

This package contains all tools available to the LLM agent.
"""

from typing import Any

# Import tools from submodules
from src.agent.tools.code_execution import execute_code, is_code_sandbox_available
from src.agent.tools.context import (
    get_conversation_context,
    get_current_message_files,
    set_conversation_context,
    set_current_message_files,
)
from src.agent.tools.file_retrieval import retrieve_file
from src.agent.tools.google_calendar import google_calendar, is_google_calendar_available
from src.agent.tools.image_generation import generate_image
from src.agent.tools.planner import (
    is_refresh_planner_dashboard_available,
    refresh_planner_dashboard,
)
from src.agent.tools.todoist import is_todoist_available, todoist
from src.agent.tools.web import FETCHABLE_BINARY_TYPES, fetch_url, web_search
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Integration tools that are disabled in anonymous mode
_INTEGRATION_TOOLS = {"todoist", "google_calendar"}


def get_available_tools() -> list[Any]:
    """Get the list of available tools, including execute_code if Docker is available.

    This function checks Docker availability on first call and caches the result.
    """
    tools: list[Any] = [fetch_url, web_search, generate_image, retrieve_file]

    # Only add execute_code if sandbox is enabled and Docker is available
    if Config.CODE_SANDBOX_ENABLED:
        # Don't check Docker availability here to avoid slow startup
        # The tool will return an error if Docker is not available when called
        tools.append(execute_code)
        logger.debug("execute_code tool added to available tools")

    # Add Todoist tool if configured
    if is_todoist_available():
        tools.append(todoist)
        logger.debug("todoist tool added to available tools")

    # Add Google Calendar tool if configured
    if is_google_calendar_available():
        tools.append(google_calendar)
        logger.debug("google_calendar tool added to available tools")

    return tools


# List of all available tools for the agent
# Note: Use get_available_tools() for dynamic tool list based on Docker availability
TOOLS = get_available_tools()


def get_tools_for_request(anonymous_mode: bool = False, is_planning: bool = False) -> list[Any]:
    """Get tools for a specific request, optionally excluding integration tools.

    Args:
        anonymous_mode: If True, excludes Todoist and Google Calendar tools.
        is_planning: If True, includes the refresh_planner_dashboard tool.

    Returns:
        List of tools to bind to the LLM for this request.
    """
    if anonymous_mode:
        tools = [t for t in TOOLS if t.name not in _INTEGRATION_TOOLS]
    else:
        tools = list(TOOLS)

    # Add refresh_planner_dashboard tool only in planner mode
    if is_planning and is_refresh_planner_dashboard_available():
        tools.append(refresh_planner_dashboard)

    return tools


# Export all public symbols
__all__ = [
    # Tools
    "fetch_url",
    "web_search",
    "generate_image",
    "execute_code",
    "retrieve_file",
    "todoist",
    "google_calendar",
    "refresh_planner_dashboard",
    # Context helpers
    "set_current_message_files",
    "get_current_message_files",
    "set_conversation_context",
    "get_conversation_context",
    # Availability checks
    "is_code_sandbox_available",
    "is_todoist_available",
    "is_google_calendar_available",
    "is_refresh_planner_dashboard_available",
    # Tool lists
    "TOOLS",
    "get_available_tools",
    "get_tools_for_request",
    # Constants
    "FETCHABLE_BINARY_TYPES",
]
