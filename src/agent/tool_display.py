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
    "research": {
        "label": "Researching",
        "label_past": "Researched",
        "icon": "search",
    },
    "delegate_task": {
        "label": "Delegating research",
        "label_past": "Delegated research",
        "icon": "sparkles",
    },
    "browser": {
        "label": "Browsing the web",
        "label_past": "Browsed",
        "icon": "globe",
    },
    "generate_image": {
        "label": "Generating image",
        "label_past": "Generated image",
        "icon": "image",
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
    "whatsapp": {
        "label": "Sending WhatsApp message",
        "label_past": "Sent WhatsApp message",
        "icon": "message",
    },
    "kv_store": {
        "label": "Accessing storage",
        "label_past": "Accessed storage",
        "icon": "database",
    },
    # Memory writes are shown like any other tool: the user should see when
    # something was learned about them, at the moment it happens, rather than
    # having to open the memories popup to find out.
    "manage_memory": {
        "label": "Updating memory",
        "label_past": "Updated memory",
        "icon": "brain",
    },
    "search_memory": {
        "label": "Searching memory",
        "label_past": "Searched memory",
        "icon": "brain",
    },
    "search_conversations": {
        "label": "Searching past conversations",
        "label_past": "Searched past conversations",
        "icon": "history",
    },
    "read_conversation": {
        "label": "Reading a past conversation",
        "label_past": "Read a past conversation",
        "icon": "history",
    },
    # Health & training. garmin_connect is one of the most-used tools in the
    # app; without an entry here it rendered as a bare "Used garmin_connect".
    "garmin_connect": {
        "label": "Reading Garmin data",
        "label_past": "Read Garmin data",
        "icon": "activity",
    },
    "garmin_workout": {
        "label": "Updating Garmin workout",
        "label_past": "Updated Garmin workout",
        "icon": "activity",
    },
    "rouvy_workout": {
        "label": "Updating Rouvy workout",
        "label_past": "Updated Rouvy workout",
        "icon": "activity",
    },
    # Places & routing
    "search_places": {
        "label": "Searching places",
        "label_past": "Searched places",
        "icon": "map-pin",
    },
    "save_place": {
        "label": "Saving a place",
        "label_past": "Saved a place",
        "icon": "map-pin",
    },
    "list_places": {
        "label": "Listing saved places",
        "label_past": "Listed saved places",
        "icon": "map-pin",
    },
    "delete_place": {
        "label": "Removing a saved place",
        "label_past": "Removed a saved place",
        "icon": "map-pin",
    },
    "get_route": {
        "label": "Planning a route",
        "label_past": "Planned a route",
        "icon": "map-pin",
    },
    # Files
    "create_file": {
        "label": "Creating a file",
        "label_past": "Created a file",
        "icon": "file",
    },
    "retrieve_file": {
        "label": "Opening a file",
        "label_past": "Opened a file",
        "icon": "file",
    },
    # Agent control
    "trigger_agent": {
        "label": "Triggering an agent",
        "label_past": "Triggered an agent",
        "icon": "robot",
    },
    "request_approval": {
        "label": "Requesting approval",
        "label_past": "Requested approval",
        "icon": "lock",
    },
    # Extract-only metadata tools (see tools/metadata.py). They do no work the
    # user asked for, but they DO emit tool_start events, so without an entry
    # here the trace showed a raw "Used cite_sources" - the single most common
    # unlabelled pill in the app.
    "cite_sources": {
        "label": "Citing sources",
        "label_past": "Cited sources",
        "icon": "sources",
    },
    "set_conversation_title": {
        "label": "Naming the conversation",
        "label_past": "Renamed the conversation",
        "icon": "edit",
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

# Place/routing tools share one detail formatter.
_PLACE_TOOLS = frozenset(
    {"search_places", "save_place", "list_places", "delete_place", "get_route"}
)


# Tools that exist but are only bound in specific contexts, so they never show
# up in get_available_tools(): planner mode, program/agent conversations, and
# the autonomous-agent tool set.
_CONDITIONAL_TOOLS = frozenset(
    {
        "refresh_planner_dashboard",
        "kv_store",
        "browser",
        "request_approval",
        "trigger_agent",
    }
)


def validate_tool_names() -> None:
    """Check TOOL_METADATA against the real tool registry, both directions.

    Runs at import time. The reverse check is the important one: a tool with no
    metadata entry silently renders in the UI as a raw "Used <function_name>"
    pill, which is how garmin_connect, kv_store and cite_sources - three of the
    five most-called tools - ended up unlabelled for months.
    """
    from src.agent.tools import get_available_tools

    actual_tool_names = {tool.name for tool in get_available_tools()}
    valid_tool_names = actual_tool_names | _CONDITIONAL_TOOLS

    unknown = set(TOOL_METADATA) - valid_tool_names
    if unknown:
        logger.warning(
            f"TOOL_METADATA contains unknown tool names: {sorted(unknown)}. "
            f"Valid tools: {sorted(valid_tool_names)}"
        )

    unlabelled = valid_tool_names - set(TOOL_METADATA)
    if unlabelled:
        logger.warning(
            "Tools missing TOOL_METADATA (they will render as raw function names "
            f"in the thinking trace): {sorted(unlabelled)}"
        )


# ============ Detail Extraction Functions ============

# Human phrasing for garmin_connect actions. Anything unmapped falls back to
# the action name with its get_ prefix stripped, so a new action still reads
# sensibly in the UI without a change here.
_GARMIN_ACTION_LABELS = {
    "get_readiness_snapshot": "readiness snapshot",
    "get_stats": "daily stats",
    "get_heart_rates": "heart rate",
    "get_sleep_data": "sleep",
    "get_stress_data": "stress",
    "get_hrv_data": "HRV",
    "get_spo2_data": "blood oxygen",
    "get_body_composition": "body composition",
    "get_activities": "recent activities",
    "get_activity_details": "activity",
    "get_training_readiness": "training readiness",
    "get_training_status": "training status",
    "get_steps": "steps",
    "get_courses": "saved routes",
    "get_course_details": "route",
}


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


def _format_garmin_detail(tool_args: dict[str, Any]) -> str:
    """Garmin read as 'what, for when' - e.g. 'sleep · 2026-09-05'."""
    action = str(tool_args.get("action", ""))
    label = _GARMIN_ACTION_LABELS.get(action, action.removeprefix("get_").replace("_", " "))

    if action == "get_activity_details":
        return f"{label} · {tool_args.get('activity_id', '')}"
    if action == "get_course_details":
        return f"{label} · course {tool_args.get('course_id', '')}"
    if action in {"get_activities", "get_courses"}:
        bits = [label]
        if tool_args.get("activity_type"):
            bits.append(str(tool_args["activity_type"]))
        if tool_args.get("limit"):
            bits.append(f"last {tool_args['limit']}")
        return " · ".join(bits)
    if tool_args.get("date_str"):
        return f"{label} · {tool_args['date_str']}"
    return label


def _format_garmin_workout_detail(tool_args: dict[str, Any]) -> str:
    """Garmin workout edit as 'action: target'."""
    action = str(tool_args.get("action", ""))
    if action == "search_exercises":
        return f"search exercises: {tool_args.get('query', '')}"
    if action == "update":
        edits = tool_args.get("edits")
        count = len(edits) if isinstance(edits, list) else None
        suffix = f" ({count} edits)" if count else ""
        return f"update workout {tool_args.get('workout_id', '')}{suffix}"
    if action in {"get", "delete"}:
        return f"{action} workout {tool_args.get('workout_id', '')}"
    return action


def _format_rouvy_detail(tool_args: dict[str, Any]) -> str:
    """Rouvy workout op as 'action: name-or-id'."""
    action = str(tool_args.get("action", ""))
    name = tool_args.get("name")
    if name:
        return f"{action}: {_snippet(str(name), 55)}"
    if tool_args.get("workout_id"):
        return f"{action}: workout {tool_args['workout_id']}"
    return action


def _format_kv_detail(tool_args: dict[str, Any]) -> str:
    """KV op as 'verb key' - the sports/language programs lean on this heavily."""
    action = str(tool_args.get("action", ""))
    key = str(tool_args.get("key") or "")
    if action == "list":
        return f"list keys{f': {key}*' if key else ''}"
    if not key:
        return action
    return f"{action}: {key}"


def _format_places_detail(tool_name: str, tool_args: dict[str, Any]) -> str | None:
    """Place/route args as the thing being looked up."""
    if tool_name == "search_places":
        query = str(tool_args.get("query") or "")
        near = str(tool_args.get("near") or "")
        if near and near != "current":
            return f"{query} near {near}"
        return query or None
    if tool_name in {"save_place", "delete_place"}:
        return str(tool_args.get("name") or "") or None
    if tool_name == "get_route":
        origin = tool_args.get("origin", "")
        destination = tool_args.get("destination", "")
        mode = tool_args.get("mode", "car")
        return f"{origin} → {destination} ({mode})"
    return None


def _snippet(text: str, limit: int) -> str:
    """First line of `text`, truncated to `limit` chars with an ellipsis."""
    line = text.strip().split("\n", 1)[0]
    return line[: limit - 1] + "…" if len(line) > limit else line


def _fetch_memory_content(memory_id: str) -> str | None:
    """Current content of a memory, for a pre-execution diff.

    extract_tool_detail runs at tool_start, before the write executes, so the
    DB still holds the OLD content here. Best-effort: returns None when there
    is no user context or the lookup fails, so the pill degrades gracefully.
    """
    if not memory_id:
        return None
    try:
        from src.agent.tools.context import get_conversation_context
        from src.db.models import db

        _, user_id = get_conversation_context()
        if not user_id:
            return None
        memory = db.get_memory(memory_id, user_id)
        return memory.content if memory else None
    except Exception:  # noqa: S110 - display nicety; never break the pill
        return None


def _format_memory_op(op: dict[str, Any]) -> str | None:
    """One memory operation as 'verb: what changed' (a compact diff)."""
    action = str(op.get("action"))
    new_content = str(op.get("content") or "").strip()
    if action == "add":
        return f"remembered: {_snippet(new_content, 55)}" if new_content else "remembered"
    if action == "update":
        old = _fetch_memory_content(str(op.get("id") or "").strip())
        if old and new_content:
            return f"updated: {_snippet(old, 35)} → {_snippet(new_content, 35)}"
        if new_content:
            return f"updated: {_snippet(new_content, 55)}"
        return "updated"
    if action == "delete":
        old = _fetch_memory_content(str(op.get("id") or "").strip())
        return f"forgot: {_snippet(old, 55)}" if old else "forgot"
    return None


def _format_memory_detail(tool_args: dict[str, Any]) -> str:
    """Summarize memory operations as a diff, e.g.
    "updated: oat milk lattes → black coffee; remembered: Has two kids".

    Shows up to two entries verbatim, then "(+N more)" to keep the pill compact.
    """
    operations = tool_args.get("operations")
    if not isinstance(operations, list):
        return "updated memory"

    parts: list[str] = []
    for op in operations:
        if isinstance(op, dict):
            label = _format_memory_op(op)
            if label:
                parts.append(label)

    if not parts:
        return "updated memory"
    if len(parts) <= 2:
        return "; ".join(parts)
    return f"{'; '.join(parts[:2])} (+{len(parts) - 2} more)"


def _fetch_conversation_title(conversation_id: str) -> str | None:
    """Title of a past conversation, for the read_conversation pill.

    Best-effort: None when there is no user context or the lookup fails.
    """
    if not conversation_id:
        return None
    try:
        from src.agent.tools.context import get_conversation_context
        from src.db.models import db

        _, user_id = get_conversation_context()
        if not user_id:
            return None
        conversation = db.get_conversation(conversation_id, user_id)
        return conversation.title if conversation else None
    except Exception:  # noqa: S110 - display nicety; never break the pill
        return None


def extract_tool_detail(tool_name: str, tool_args: dict[str, Any]) -> str | None:
    """Extract a human-readable detail string from complete tool arguments.

    This is used when we have the complete tool_calls with parsed args dict.

    Args:
        tool_name: Name of the tool being called
        tool_args: Parsed arguments dictionary

    Returns:
        Detail string to display in UI, or None if no detail available
    """
    if tool_name == "research" and tool_args.get("question"):
        return str(tool_args["question"])
    elif tool_name == "delegate_task" and tool_args.get("task"):
        return str(tool_args["task"])[:200]
    elif tool_name == "web_search" and (tool_args.get("query") or tool_args.get("queries")):
        parts = [str(tool_args["query"])] if tool_args.get("query") else []
        batched = tool_args.get("queries")
        if isinstance(batched, list):
            parts.extend(str(q) for q in batched)
        return " | ".join(parts)
    elif tool_name == "browser" and "action" in tool_args:
        action = str(tool_args["action"])
        if action == "navigate" and "url" in tool_args:
            return f"navigate: {tool_args['url']}"
        if action in ("click", "type") and "selector" in tool_args:
            return f"{action}: {str(tool_args['selector'])[:50]}"
        return action
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
    elif tool_name == "manage_memory" and "operations" in tool_args:
        return _format_memory_detail(tool_args)
    elif tool_name == "search_memory" and tool_args.get("query"):
        return str(tool_args["query"])
    elif tool_name == "search_conversations" and tool_args.get("query"):
        return str(tool_args["query"])
    elif tool_name == "read_conversation" and tool_args.get("conversation_id"):
        return _fetch_conversation_title(str(tool_args["conversation_id"]).strip())
    elif tool_name == "garmin_connect" and "action" in tool_args:
        return _format_garmin_detail(tool_args)
    elif tool_name == "garmin_workout" and "action" in tool_args:
        return _format_garmin_workout_detail(tool_args)
    elif tool_name == "rouvy_workout" and "action" in tool_args:
        return _format_rouvy_detail(tool_args)
    elif tool_name == "kv_store" and "action" in tool_args:
        return _format_kv_detail(tool_args)
    elif tool_name in _PLACE_TOOLS:
        return _format_places_detail(tool_name, tool_args)
    elif tool_name == "whatsapp" and tool_args.get("message"):
        return _snippet(str(tool_args["message"]), 60)
    elif tool_name == "create_file" and tool_args.get("filename"):
        return str(tool_args["filename"])
    elif tool_name == "retrieve_file" and tool_args.get("message_id"):
        return f"file {tool_args.get('file_index', 0)} from an earlier message"
    elif tool_name == "trigger_agent" and tool_args.get("agent_name"):
        return str(tool_args["agent_name"])
    elif tool_name == "request_approval" and tool_args.get("action_description"):
        return _snippet(str(tool_args["action_description"]), 70)
    elif tool_name == "cite_sources":
        sources = tool_args.get("sources")
        if isinstance(sources, list) and sources:
            return f"{len(sources)} source{'s' if len(sources) != 1 else ''}"
        return None
    elif tool_name == "set_conversation_title" and tool_args.get("title"):
        return str(tool_args["title"])
    return None


# Run validation on import to catch tool name mismatches early
validate_tool_names()
