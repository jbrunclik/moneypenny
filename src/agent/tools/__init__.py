"""Agent tools package.

This package contains all tools available to the LLM agent.
"""

from collections.abc import Callable
from typing import Any

# Import tools from submodules
from langchain_core.tools import BaseTool
from pydantic import BaseModel
from pydantic.config import JsonDict

from src.agent.permissions import base_tool
from src.agent.tools.agent_kv import kv_store
from src.agent.tools.artifacts import create_artifact, read_artifact, update_artifact
from src.agent.tools.attachment import create_file
from src.agent.tools.browser import browser, is_browser_available
from src.agent.tools.code_execution import execute_code, is_code_sandbox_available
from src.agent.tools.context import (
    get_agent_name,
    get_conversation_context,
    get_current_message_files,
    get_location_context,
    get_standing_namespace,
    set_agent_name,
    set_conversation_context,
    set_current_message_files,
    set_location_context,
    set_standing_namespace,
)
from src.agent.tools.conversation_search import read_conversation, search_conversations
from src.agent.tools.deep_research import propose_deep_research
from src.agent.tools.delegate import delegate_task
from src.agent.tools.file_retrieval import retrieve_file
from src.agent.tools.garmin import garmin_connect, is_garmin_available
from src.agent.tools.garmin_workout import garmin_workout
from src.agent.tools.google_calendar import google_calendar, is_google_calendar_available
from src.agent.tools.image_generation import generate_image
from src.agent.tools.memory import manage_memory, search_memory
from src.agent.tools.metadata import (
    EXTRACT_ONLY_TOOL_NAMES,
    record_conversation_facts,
    set_conversation_title,
)
from src.agent.tools.places import (
    delete_place,
    get_route,
    is_places_available,
    list_places,
    save_place,
    search_places,
)
from src.agent.tools.planner import (
    is_refresh_planner_dashboard_available,
    refresh_planner_dashboard,
)
from src.agent.tools.request_approval import ApprovalRequestedException, request_approval
from src.agent.tools.research import research
from src.agent.tools.rouvy import is_rouvy_available, rouvy_workout
from src.agent.tools.scheduling import schedule
from src.agent.tools.skills import load_skill
from src.agent.tools.standing_settings import edit_standing_chat
from src.agent.tools.todoist import is_todoist_available, todoist
from src.agent.tools.trigger_agent import trigger_agent
from src.agent.tools.web import fetch_url, web_search
from src.agent.tools.web_content import FETCHABLE_BINARY_TYPES
from src.agent.tools.whatsapp import is_whatsapp_available, whatsapp
from src.config import Config
from src.db.models import db
from src.db.models.dataclasses import Agent
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Integration tools that are disabled in anonymous mode
_INTEGRATION_TOOLS = {"todoist", "google_calendar", "garmin_connect", "garmin_workout"}

# Tools withheld in anonymous mode on top of the integrations. manage_memory is
# unbound rather than filtered later so the model cannot even attempt a write it
# is not allowed to make.
_ANONYMOUS_EXCLUDED_TOOLS = _INTEGRATION_TOOLS | {
    "manage_memory",
    "search_memory",
    # Write persistent user data (saved places) - not allowed from anonymous chats
    "save_place",
    "delete_place",
    # Reading past conversations would pull the history the user deliberately
    # stepped away from back into an anonymous chat.
    "search_conversations",
    "read_conversation",
}


def get_available_tools() -> list[Any]:
    """Get the list of available tools, including execute_code if Docker is available.

    This function checks Docker availability on first call and caches the result.
    """
    tools: list[Any] = [
        fetch_url,
        web_search,
        research,
        delegate_task,
        generate_image,
        retrieve_file,
        create_file,
        load_skill,
        set_conversation_title,
        manage_memory,
        search_memory,
        search_conversations,
        read_conversation,
    ]

    # Inline artifacts (sandboxed HTML/JS under the reply); never granted to
    # autonomous agents - their output is push and digest text
    if Config.ARTIFACTS_ENABLED:
        tools.extend([create_artifact, update_artifact, read_artifact])

    # Only add browser if enabled and Playwright is installed
    if Config.BROWSER_ENABLED and is_browser_available():
        tools.append(browser)
        logger.debug("browser tool added to available tools")

    # Only add execute_code if sandbox is enabled and Docker is available
    if Config.CODE_SANDBOX_ENABLED:
        # Don't check Docker availability here to avoid slow startup
        # The tool will return an error if Docker is not available when called
        tools.append(execute_code)
        logger.debug("execute_code tool added to available tools")

    # Add places & routing tools if the Mapy.com API key is configured
    if is_places_available():
        tools.extend([search_places, get_route, save_place, list_places, delete_place])
        logger.debug("places tools added to available tools")

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
        tools.append(garmin_workout)
        logger.debug("garmin_connect + garmin_workout tools added to available tools")

    # Add Rouvy tool if the browser (Chromium, needed for login) is available
    if is_rouvy_available():
        tools.append(rouvy_workout)
        logger.debug("rouvy_workout tool added to available tools")

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
    return bool(user and user.whatsapp_phone)


def _integration_available(tool_name: str, whatsapp_available: Callable[[], bool]) -> bool:
    """False for an integration tool this deployment cannot run; True for any other tool."""
    checks: dict[str, Callable[[], bool]] = {
        "todoist": is_todoist_available,
        "google_calendar": is_google_calendar_available,
        "garmin_connect": is_garmin_available,
        "garmin_workout": is_garmin_available,
        "execute_code": lambda: Config.CODE_SANDBOX_ENABLED,
        "browser": lambda: Config.BROWSER_ENABLED and is_browser_available(),
        "rouvy_workout": is_rouvy_available,
        "whatsapp": whatsapp_available,
    }
    check = checks.get(tool_name)
    return check is None or check()


def _add_permitted_tools(
    tools: list[Any], permissions: list[str], whatsapp_available: Callable[[], bool]
) -> None:
    """Append each permitted, available tool not already in `tools`."""
    for tool_name in {base_tool(p) for p in permissions}:
        tool = _TOOL_MAP.get(tool_name)
        if tool is None or tool in tools:
            continue
        # Check availability for integration tools
        if _integration_available(tool_name, whatsapp_available):
            tools.append(tool)


def _ordinary_chat_tools(anonymous_mode: bool) -> list[BaseTool]:
    """Chat-only tools: every interactive chat but the planner (never unattended runs)."""
    tools: list[BaseTool] = []
    # Deep research offers: those have their own cost and approval models
    if Config.DEEP_RESEARCH_ENABLED:
        tools.append(propose_deep_research)
    # Conversation facts are kept in every non-anonymous chat (ordinary and
    # standing); an anonymous chat keeps nothing, so the tool would lie "recorded"
    if Config.CONVERSATION_FACTS_ENABLED and not anonymous_mode:
        tools.append(record_conversation_facts)
    # Reminders and recurring tasks from chat: not in anonymous chats, and never
    # for agents - a scheduled run must not schedule more
    if not anonymous_mode:
        tools.append(schedule)
    return tools


def get_tools_for_request(
    anonymous_mode: bool = False,
    is_planning: bool = False,
    standing: bool = False,
) -> list[Any]:
    """The tools to bind for an interactive chat turn.

    Every chat but the planner gets the ordinary chat tools; a standing chat
    (agent / sports / language) also gets `kv_store` for its own namespace.
    Unattended agent runs use get_tools_for_agent instead.

    Args:
        anonymous_mode: If True, excludes personal integrations (Todoist, Calendar...).
        is_planning: If True, the planner's tools (refresh_planner_dashboard).
        standing: If True, a standing chat - adds kv_store.
    """
    # Computed per request (not a frozen import-time constant) so availability
    # changes - Playwright installed, an integration configured - apply without
    # a process restart.
    available = get_available_tools()
    if anonymous_mode:
        tools = [t for t in available if t.name not in _ANONYMOUS_EXCLUDED_TOOLS]
    else:
        tools = available

    if not is_planning:
        tools = [*tools, *_ordinary_chat_tools(anonymous_mode)]

    if is_planning and is_refresh_planner_dashboard_available():
        tools.append(refresh_planner_dashboard)

    if standing and kv_store not in tools:
        tools.append(kv_store)
    if standing:
        # An agent's chat: it may propose changes to its own settings (the
        # tool refuses in chats without an agent)
        tools.append(edit_standing_chat)

    return tools


# Map of tool names to tool functions for agent filtering
_TOOL_MAP: dict[str, Any] = {
    "web_search": web_search,
    "fetch_url": fetch_url,
    "research": research,
    "delegate_task": delegate_task,
    "browser": browser,
    "generate_image": generate_image,
    "retrieve_file": retrieve_file,
    "create_file": create_file,
    "load_skill": load_skill,
    "execute_code": execute_code,
    "todoist": todoist,
    "google_calendar": google_calendar,
    "garmin_connect": garmin_connect,
    "garmin_workout": garmin_workout,
    "rouvy_workout": rouvy_workout,
    "trigger_agent": trigger_agent,
    "whatsapp": whatsapp,
    "manage_memory": manage_memory,
    "search_memory": search_memory,
    "search_conversations": search_conversations,
    "read_conversation": read_conversation,
    "kv_store": kv_store,
    "search_places": search_places,
    "get_route": get_route,
    "save_place": save_place,
    "list_places": list_places,
    "delete_place": delete_place,
}


# Tools that are real but never appear in _TOOL_MAP: they are bound by a
# specific caller rather than selected by agent permissions.
_NON_PERMISSIONED_TOOLS = frozenset(
    {
        "set_conversation_title",  # metadata tool, always bound
        "record_conversation_facts",  # metadata tool, chats only
        "refresh_planner_dashboard",  # planner mode only
        "request_approval",  # autonomous agents only
        "propose_deep_research",  # ordinary chats only, never for agents
        "schedule",  # ordinary non-anonymous chats only: a scheduled run must not schedule
        "edit_standing_chat",  # standing chats and their jobs, never a grant
        # Inline artifacts: chats only, never granted to agents
        "create_artifact",
        "update_artifact",
        "read_artifact",
    }
)


def get_all_tool_names() -> set[str]:
    """Every tool name that exists, regardless of local configuration.

    Distinct from get_available_tools(), which is environment-dependent -
    integration tools only register when their package/credentials are present.
    Use this (never get_available_tools) to decide whether a tool name is
    legitimate, or the answer changes between a dev laptop and CI.
    """
    return set(_TOOL_MAP) | set(_NON_PERMISSIONED_TOOLS)


def _unrestricted_agent_tools(agent: Agent) -> list[Any]:
    """The extra tools of an agent with no permission list: every available one."""
    tools: list[Any] = []
    if is_todoist_available():
        tools.append(todoist)
    if is_google_calendar_available():
        tools.append(google_calendar)
    if is_garmin_available():
        tools.append(garmin_connect)
        tools.append(garmin_workout)
    if is_rouvy_available():
        tools.append(rouvy_workout)
    # WhatsApp requires both app config AND user phone number
    if _is_whatsapp_available_for_user(agent.user_id):
        tools.append(whatsapp)
    if Config.CODE_SANDBOX_ENABLED:
        tools.append(execute_code)
    if Config.BROWSER_ENABLED and is_browser_available():
        tools.append(browser)
    tools.append(generate_image)
    # Unrestricted agents keep memory access; restricted ones must ask for it
    tools.append(manage_memory)
    # Agent-to-agent handoff passes text into another agent's run, so
    # restricted agents must be granted it like any other capability
    tools.append(trigger_agent)
    return tools


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
    # Always include basic safe tools + metadata tools.
    #
    # manage_memory is deliberately excluded: an unattended run that reads the
    # web could otherwise persist attacker-controlled text into the user's
    # long-term memory, which is injected into every later conversation. Agents
    # that genuinely need it must list it in tool_permissions (or run with
    # unrestricted permissions), and the tool re-checks that at call time.
    tools: list[Any] = [
        fetch_url,
        web_search,
        research,
        retrieve_file,
        create_file,
        load_skill,
    ]

    # Add request_approval for sensitive actions
    tools.append(request_approval)

    # Add kv_store for persistent storage
    tools.append(kv_store)

    # A standing job may ask the user to change its own settings (approval only)
    tools.append(edit_standing_chat)

    # If agent has specific permissions (including empty list), filter tools
    if agent.tool_permissions is not None:
        # Explicit permission list - only add permitted tools.
        # WhatsApp requires both app config AND user phone number
        _add_permitted_tools(
            tools,
            agent.tool_permissions,
            lambda: _is_whatsapp_available_for_user(agent.user_id),
        )
    else:
        # No specific permissions (None) - add all available integration tools
        tools.extend(_unrestricted_agent_tools(agent))

    logger.debug(
        "Tools for agent",
        extra={
            "agent_id": agent.id,
            "tool_names": [t.name for t in tools],
        },
    )
    return tools


# Export all public symbols
def _pop_schema_description(schema: JsonDict) -> None:
    schema.pop("description", None)


def _drop_duplicate_schema_descriptions(tools: list[BaseTool]) -> None:
    """Stop sending each tool's docstring twice.

    langchain-google-genai turns a BaseTool's args JSON schema into the
    declaration's `parameters`, keeping the schema's top-level description -
    the same docstring LangChain already sends as the function description.
    That duplicate was 10.2k of the 24.5k tool tokens on every model call
    (measured Nov 2026). Dropped from the JSON schema only (argument
    validation is unchanged), and only where it is that exact duplicate.
    """
    for tool in tools:
        args_model = tool.args_schema
        if not (isinstance(args_model, type) and issubclass(args_model, BaseModel)):
            continue
        if "json_schema_extra" in args_model.model_config:
            continue
        if args_model.model_json_schema().get("description") != tool.description:
            continue
        # A fresh dict: never mutate a config another model might share
        args_model.model_config = {
            **args_model.model_config,
            "json_schema_extra": _pop_schema_description,
        }


_drop_duplicate_schema_descriptions(
    [t for t in list(globals().values()) if isinstance(t, BaseTool)]
)


__all__ = [  # noqa: RUF022 - grouped by kind, not alphabetically
    # Tools
    "fetch_url",
    "web_search",
    "research",
    "delegate_task",
    "browser",
    "generate_image",
    "execute_code",
    "retrieve_file",
    "create_file",
    "load_skill",
    "todoist",
    "google_calendar",
    "garmin_connect",
    "garmin_workout",
    "rouvy_workout",
    "refresh_planner_dashboard",
    "trigger_agent",
    "request_approval",
    "whatsapp",
    "set_conversation_title",
    "record_conversation_facts",
    "manage_memory",
    "search_memory",
    "search_conversations",
    "read_conversation",
    "kv_store",
    "search_places",
    "get_route",
    "save_place",
    "list_places",
    "delete_place",
    # Metadata tool constants
    "EXTRACT_ONLY_TOOL_NAMES",
    # Exceptions
    "ApprovalRequestedException",
    # Context helpers
    "set_current_message_files",
    "get_current_message_files",
    "set_conversation_context",
    "get_conversation_context",
    "set_agent_name",
    "get_agent_name",
    "set_standing_namespace",
    "get_standing_namespace",
    "set_location_context",
    "get_location_context",
    # Availability checks
    "is_browser_available",
    "is_code_sandbox_available",
    "is_todoist_available",
    "is_google_calendar_available",
    "is_garmin_available",
    "is_refresh_planner_dashboard_available",
    "is_whatsapp_available",
    "is_places_available",
    # Tool lists
    "get_available_tools",
    "get_tools_for_request",
    "get_tools_for_agent",
    # Constants
    "FETCHABLE_BINARY_TYPES",
]
