"""Agent tools package.

This package contains all tools available to the LLM agent.
"""

from typing import Any

# Import tools from submodules
from src.agent.tools.agent_kv import kv_store
from src.agent.tools.code_execution import execute_code, is_code_sandbox_available
from src.agent.tools.context import (
    get_agent_name,
    get_conversation_context,
    get_current_message_files,
    set_agent_name,
    set_conversation_context,
    set_current_message_files,
)
from src.agent.tools.file_retrieval import retrieve_file
from src.agent.tools.garmin import garmin_connect, is_garmin_available
from src.agent.tools.google_calendar import google_calendar, is_google_calendar_available
from src.agent.tools.image_generation import generate_image
from src.agent.tools.metadata import METADATA_TOOL_NAMES, cite_sources, manage_memory
from src.agent.tools.planner import (
    is_refresh_planner_dashboard_available,
    refresh_planner_dashboard,
)
from src.agent.tools.request_approval import ApprovalRequestedException, request_approval
from src.agent.tools.todoist import is_todoist_available, todoist
from src.agent.tools.trigger_agent import trigger_agent
from src.agent.tools.web import FETCHABLE_BINARY_TYPES, fetch_url, web_search
from src.agent.tools.whatsapp import is_whatsapp_available, whatsapp
from src.config import Config
from src.db.models import db
from src.db.models.dataclasses import Agent
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Integration tools that are disabled in anonymous mode
_INTEGRATION_TOOLS = {"todoist", "google_calendar", "garmin_connect"}


def get_available_tools() -> list[Any]:
    """Get the list of available tools, including execute_code if Docker is available.

    This function checks Docker availability on first call and caches the result.
    """
    tools: list[Any] = [
        fetch_url,
        web_search,
        generate_image,
        retrieve_file,
        cite_sources,
        manage_memory,
    ]

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

    # Add Garmin Connect tool if package is installed
    if is_garmin_available():
        tools.append(garmin_connect)
        logger.debug("garmin_connect tool added to available tools")

    # Add WhatsApp tool if configured
    if is_whatsapp_available():
        tools.append(whatsapp)
        logger.debug("whatsapp tool added to available tools")

    return tools


def _is_whatsapp_available_for_user(user_id: str) -> bool:
    """Check if WhatsApp is available for a specific user.

    WhatsApp requires both:
    1. App-level configuration (PHONE_NUMBER_ID, ACCESS_TOKEN, TEMPLATE_NAME)
    2. User has configured their WhatsApp phone number in settings

    Args:
        user_id: The user's ID

    Returns:
        True if WhatsApp can be used by this user, False otherwise
    """
    if not is_whatsapp_available():
        return False

    user = db.get_user_by_id(user_id)
    if not user or not user.whatsapp_phone:
        return False

    return True


# List of all available tools for the agent
# Note: Use get_available_tools() for dynamic tool list based on Docker availability
TOOLS = get_available_tools()


def get_tools_for_request(
    anonymous_mode: bool = False,
    is_planning: bool = False,
    agent_tool_permissions: list[str] | None = None,
) -> list[Any]:
    """Get tools for a specific request, optionally excluding integration tools.

    Args:
        anonymous_mode: If True, excludes Todoist and Google Calendar tools.
        is_planning: If True, includes the refresh_planner_dashboard tool.
        agent_tool_permissions: If provided, only include these tools plus basic safe tools.
            This is used for autonomous agents to restrict their capabilities.

    Returns:
        List of tools to bind to the LLM for this request.
    """
    # For autonomous agents with specific permissions
    if agent_tool_permissions is not None:
        # Always include basic safe tools + metadata tools
        tools: list[Any] = [fetch_url, web_search, retrieve_file, cite_sources, manage_memory]

        # Add permitted tools
        for tool_name in agent_tool_permissions:
            if tool_name in _TOOL_MAP:
                tool = _TOOL_MAP[tool_name]
                if tool not in tools:
                    # Check availability for integration tools
                    if tool_name == "todoist" and not is_todoist_available():
                        continue
                    if tool_name == "google_calendar" and not is_google_calendar_available():
                        continue
                    if tool_name == "execute_code" and not Config.CODE_SANDBOX_ENABLED:
                        continue
                    if tool_name == "garmin_connect" and not is_garmin_available():
                        continue
                    if tool_name == "whatsapp" and not is_whatsapp_available():
                        continue
                    tools.append(tool)

        return tools

    # Standard request handling
    if anonymous_mode:
        tools = [t for t in TOOLS if t.name not in _INTEGRATION_TOOLS]
    else:
        tools = list(TOOLS)

    # Add refresh_planner_dashboard tool only in planner mode
    if is_planning and is_refresh_planner_dashboard_available():
        tools.append(refresh_planner_dashboard)

    return tools


# Map of tool names to tool functions for agent filtering
_TOOL_MAP: dict[str, Any] = {
    "web_search": web_search,
    "fetch_url": fetch_url,
    "generate_image": generate_image,
    "retrieve_file": retrieve_file,
    "execute_code": execute_code,
    "todoist": todoist,
    "google_calendar": google_calendar,
    "garmin_connect": garmin_connect,
    "trigger_agent": trigger_agent,
    "whatsapp": whatsapp,
    "cite_sources": cite_sources,
    "manage_memory": manage_memory,
    "kv_store": kv_store,
}


def get_tools_for_agent(agent: Agent) -> list[Any]:
    """Get tools for an autonomous agent based on its permissions.

    Args:
        agent: The agent with tool_permissions

    Returns:
        List of tools the agent is allowed to use

    Note:
        - tool_permissions=None: No restrictions, agent gets all available tools
        - tool_permissions=[]: Explicitly no extra tools, only basic safe tools
        - tool_permissions=["todoist", ...]: Only these specific tools plus basic safe tools
    """
    # Always include basic safe tools + metadata tools
    tools: list[Any] = [fetch_url, web_search, retrieve_file, cite_sources, manage_memory]

    # Add request_approval for sensitive actions
    tools.append(request_approval)

    # Add trigger_agent for agent-to-agent communication
    tools.append(trigger_agent)

    # Add kv_store for persistent storage
    tools.append(kv_store)

    # If agent has specific permissions (including empty list), filter tools
    if agent.tool_permissions is not None:
        # Explicit permission list - only add permitted tools
        for tool_name in agent.tool_permissions:
            if tool_name in _TOOL_MAP:
                tool = _TOOL_MAP[tool_name]
                if tool not in tools:
                    # Check availability for integration tools
                    if tool_name == "todoist" and not is_todoist_available():
                        continue
                    if tool_name == "google_calendar" and not is_google_calendar_available():
                        continue
                    if tool_name == "garmin_connect" and not is_garmin_available():
                        continue
                    if tool_name == "execute_code" and not Config.CODE_SANDBOX_ENABLED:
                        continue
                    # WhatsApp requires both app config AND user phone number
                    if tool_name == "whatsapp" and not _is_whatsapp_available_for_user(
                        agent.user_id
                    ):
                        continue
                    tools.append(tool)
    else:
        # No specific permissions (None) - add all available integration tools
        if is_todoist_available():
            tools.append(todoist)
        if is_google_calendar_available():
            tools.append(google_calendar)
        if is_garmin_available():
            tools.append(garmin_connect)
        # WhatsApp requires both app config AND user phone number
        if _is_whatsapp_available_for_user(agent.user_id):
            tools.append(whatsapp)
        if Config.CODE_SANDBOX_ENABLED:
            tools.append(execute_code)
        tools.append(generate_image)

    logger.debug(
        "Tools for agent",
        extra={
            "agent_id": agent.id,
            "tool_names": [t.name for t in tools],
        },
    )
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
    "garmin_connect",
    "refresh_planner_dashboard",
    "trigger_agent",
    "request_approval",
    "whatsapp",
    "cite_sources",
    "manage_memory",
    "kv_store",
    # Metadata tool constants
    "METADATA_TOOL_NAMES",
    # Exceptions
    "ApprovalRequestedException",
    # Context helpers
    "set_current_message_files",
    "get_current_message_files",
    "set_conversation_context",
    "get_conversation_context",
    "set_agent_name",
    "get_agent_name",
    # Availability checks
    "is_code_sandbox_available",
    "is_todoist_available",
    "is_google_calendar_available",
    "is_garmin_available",
    "is_refresh_planner_dashboard_available",
    "is_whatsapp_available",
    # Tool lists
    "TOOLS",
    "get_available_tools",
    "get_tools_for_request",
    "get_tools_for_agent",
    # Constants
    "FETCHABLE_BINARY_TYPES",
]
