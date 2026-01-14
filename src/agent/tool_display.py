"""Tool display metadata and formatting for the chat agent.

This module contains tool metadata for UI display and functions
for extracting human-readable details from tool calls.
"""

from typing import Any

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# ============ Tool Metadata ============

# Tool metadata for display in the UI
# Maps tool function name to display information
# icon: key used by frontend to look up SVG icon (search, link, sparkles, code, checklist)
# IMPORTANT: Tool names here must match the @tool decorated function names in tools.py
TOOL_METADATA: dict[str, dict[str, str]] = {
    "web_search": {
        "label": "Searching the web",
        "label_past": "Searched",
        "icon": "search",
    },
    "fetch_url": {
        "label": "Fetching page",
        "label_past": "Fetched",
        "icon": "link",
    },
    "generate_image": {
        "label": "Generating image",
        "label_past": "Generated image",
        "icon": "sparkles",
    },
    "execute_code": {
        "label": "Running code",
        "label_past": "Ran code",
        "icon": "code",
    },
    "todoist": {
        "label": "Managing tasks",
        "label_past": "Managed tasks",
        "icon": "checklist",
    },
    "refresh_planner_dashboard": {
        "label": "Refreshing planner",
        "label_past": "Refreshed planner",
        "icon": "refresh",
    },
}

# Check if Google Calendar is configured
_GOOGLE_CALENDAR_CONFIGURED = bool(
    Config.GOOGLE_CALENDAR_CLIENT_ID and Config.GOOGLE_CALENDAR_CLIENT_SECRET
)

if _GOOGLE_CALENDAR_CONFIGURED:
    TOOL_METADATA["google_calendar"] = {
        "label": "Organizing calendar",
        "label_past": "Organized calendar",
        "icon": "calendar",
    }

# ============ Tools with Detail Extraction ============

# Tools that have custom detail extraction logic in _extract_tool_detail
# IMPORTANT: Must match function names in tools.py - verified at import time below
_detail_tools = {
    "web_search",
    "fetch_url",
    "generate_image",
    "execute_code",
    "todoist",
}
if _GOOGLE_CALENDAR_CONFIGURED:
    _detail_tools.add("google_calendar")

TOOLS_WITH_DETAIL_EXTRACTION = frozenset(_detail_tools)


def validate_tool_names() -> None:
    """Validate that tool names in metadata and detail extraction match actual tools.

    This runs at import time to catch mismatches early during development.
    """
    from src.agent.tools import TOOLS

    actual_tool_names = {tool.name for tool in TOOLS}

    # Add conditional tools that are only available in specific contexts
    # refresh_planner_dashboard is only added in planner mode via get_tools_for_request()
    conditional_tools = {"refresh_planner_dashboard"}
    valid_tool_names = actual_tool_names | conditional_tools

    # Check TOOL_METADATA
    invalid_metadata_names = set(TOOL_METADATA.keys()) - valid_tool_names
    if invalid_metadata_names:
        logger.warning(
            f"TOOL_METADATA contains unknown tool names: {invalid_metadata_names}. "
            f"Valid tools: {valid_tool_names}"
        )

    # Check TOOLS_WITH_DETAIL_EXTRACTION
    invalid_detail_names = TOOLS_WITH_DETAIL_EXTRACTION - valid_tool_names
    if invalid_detail_names:
        logger.warning(
            f"TOOLS_WITH_DETAIL_EXTRACTION contains unknown tool names: {invalid_detail_names}. "
            f"Valid tools: {valid_tool_names}"
        )


# ============ Detail Extraction Functions ============


def _format_todoist_detail(tool_args: dict[str, Any]) -> str:
    """Format Todoist tool args into a human-readable detail string.

    Args:
        tool_args: Parsed arguments dictionary with 'action' and other params

    Returns:
        Detail string like "list_tasks: today" or "add_task: Buy milk"
    """
    action = str(tool_args.get("action", ""))
    if action == "list_tasks":
        filter_str = tool_args.get("filter_string") or tool_args.get("filter", "all")
        return f"list_tasks: {filter_str}"

    if action == "list_sections":
        project_id = tool_args.get("project_id", "") or "?"
        return f"list_sections: project {project_id}"

    if action in {"add_task", "update_task"}:
        task_label = tool_args.get("content") or tool_args.get("task_id", "")
        return f"{action}: {str(task_label)[:60]}"

    if action in {"complete_task", "uncomplete_task", "delete_task", "reopen_task", "get_task"}:
        return f"{action}: {tool_args.get('task_id', '')}"

    if action in {"add_project", "update_project"}:
        project_label = tool_args.get("project_name") or tool_args.get("project_id", "")
        return f"{action}: {project_label}"

    if action in {"delete_project", "archive_project", "unarchive_project", "get_project"}:
        return f"{action}: {tool_args.get('project_id', '')}"

    if action in {"share_project", "unshare_project"}:
        email = tool_args.get("collaborator_email", "")
        return f"{action}: {email}"

    if action in {"add_section", "update_section"}:
        section_name = tool_args.get("section_name") or tool_args.get("section_id", "")
        return f"{action}: {section_name}"

    if action in {"delete_section", "get_section"}:
        return f"{action}: {tool_args.get('section_id', '')}"

    if action == "list_projects":
        return "list_projects"

    return action


def _format_calendar_detail(tool_args: dict[str, Any]) -> str:
    """Format Google Calendar tool args into a human-readable detail string.

    Args:
        tool_args: Parsed arguments dictionary with 'action' and other params

    Returns:
        Detail string like "list_events: primary 2024-01-01 → 2024-01-07"
    """
    action = str(tool_args.get("action", ""))
    calendar_id = tool_args.get("calendar_id", "primary")

    if action == "list_events":
        start = tool_args.get("time_min")
        end = tool_args.get("time_max")
        if start and end:
            return f"list_events: {calendar_id} {start} → {end}"
        return f"list_events: {calendar_id}"
    if action == "list_calendars":
        return "list_calendars"
    if action == "create_event":
        summary = tool_args.get("summary", "")
        return f"create_event: {summary}"
    if action == "update_event":
        summary = tool_args.get("summary")
        event_id = tool_args.get("event_id", "")
        if summary:
            return f"update_event: {summary}"
        return f"update_event: {event_id}"
    if action == "delete_event":
        return f"delete_event: {tool_args.get('event_id', '')}"
    if action == "respond_event":
        status = tool_args.get("response_status", "")
        return f"respond_event: {status}"
    if action == "get_event":
        return f"get_event: {tool_args.get('event_id', '')}"
    return action


def extract_tool_detail(tool_name: str, tool_args: dict[str, Any]) -> str | None:
    """Extract a human-readable detail string from complete tool arguments.

    This is used when we have the complete tool_calls with parsed args dict.

    Args:
        tool_name: Name of the tool being called
        tool_args: Parsed arguments dictionary

    Returns:
        Detail string to display in UI, or None if no detail available
    """
    if tool_name == "web_search" and "query" in tool_args:
        return str(tool_args["query"])
    elif tool_name == "fetch_url" and "url" in tool_args:
        return str(tool_args["url"])
    elif tool_name == "generate_image" and "prompt" in tool_args:
        return str(tool_args["prompt"])
    elif tool_name == "execute_code" and "code" in tool_args:
        # Show first line of code as detail
        code_preview = str(tool_args["code"]).split("\n")[0][:50]
        return code_preview
    elif tool_name == "todoist" and "action" in tool_args:
        return _format_todoist_detail(tool_args)
    elif tool_name == "google_calendar" and "action" in tool_args:
        return _format_calendar_detail(tool_args)
    return None


# Run validation on import to catch tool name mismatches early
validate_tool_names()
