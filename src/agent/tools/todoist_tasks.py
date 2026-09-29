"""Todoist task actions (list/get/add/update/move/complete/reopen/delete) and task formatting."""

from __future__ import annotations

from typing import Any

from src.agent.tools import todoist_client
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


def format_task(
    task: dict[str, Any],
    section_map: dict[str, str] | None = None,
    project_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Format a task response for readability.

    Args:
        task: Raw task data from Todoist API
        section_map: Optional mapping of section_id -> section_name
        project_map: Optional mapping of project_id -> project_name
    """
    formatted: dict[str, Any] = {
        "id": task["id"],
        "content": task["content"],
        "description": task.get("description", ""),
        "priority": task.get("priority", 1),
        "labels": task.get("labels", []),
        "is_completed": task.get("checked", False),
    }
    # Due date and recurrence
    if task.get("due"):
        formatted["due"] = task["due"].get("string") or task["due"].get("date")
        formatted["is_recurring"] = task["due"].get("is_recurring", False)
    # Project and project name
    if task.get("project_id"):
        formatted["project_id"] = task["project_id"]
        if project_map and task["project_id"] in project_map:
            formatted["project_name"] = project_map[task["project_id"]]
    # Section info - important for context (sections organize tasks within projects)
    if task.get("section_id"):
        formatted["section_id"] = task["section_id"]
        if section_map and task["section_id"] in section_map:
            formatted["section_name"] = section_map[task["section_id"]]
    # Parent task ID for subtask hierarchy
    if task.get("parent_id"):
        formatted["parent_id"] = task["parent_id"]
    # Assignment information (API v1: responsible_uid, assigned_by_uid)
    if task.get("responsible_uid"):
        formatted["assignee_id"] = task["responsible_uid"]
    if task.get("assigned_by_uid"):
        formatted["assigner_id"] = task["assigned_by_uid"]
    # Duration/time estimate
    if task.get("duration"):
        duration = task["duration"]
        formatted["duration"] = f"{duration.get('amount', 0)} {duration.get('unit', 'minute')}"
    # Comment count (API v1: note_count)
    if task.get("note_count", 0) > 0:
        formatted["comment_count"] = task["note_count"]
    return formatted


# Todoist rejects malformed filter strings with this error (error_code 55)
_INVALID_FILTER_MARKERS = ("INVALID_SEARCH", '"error_code":55', "search query is incorrect")


# Known-good filter strings shown to the model after a rejected filter
_VALID_FILTER_EXAMPLES = [
    "today",
    "overdue | today",
    "7 days",
    "no date",
    "p1 & overdue",
    "#Work",
    "#Work & today",
    "@waiting_for",
    "search: dentist",
]


def _invalid_filter_result(filter_string: str) -> dict[str, Any]:
    """Actionable result for a filter string Todoist rejected.

    The raw API error ("The search query is incorrect") left the model
    guessing - invalid filters were the top Todoist failure in Sep 2026.
    """
    logger.warning("Todoist rejected filter", extra={"filter_string": filter_string})
    return {
        "action": "list_tasks",
        "error": (
            f"Todoist rejected the filter {filter_string!r} (invalid filter syntax). "
            "Filters use Todoist's query language, not natural language: dates "
            "('today', '7 days', 'no date'), priorities ('p1'), projects ('#Name'), "
            "labels ('@name') and free-text search ('search: word'), combined with "
            "& (and), | (or), ! (not). Retry with a valid filter, or omit "
            "filter_string to list all tasks and filter them yourself."
        ),
        "failed_filter": filter_string,
        "valid_examples": _VALID_FILTER_EXAMPLES,
        "retriable": True,
    }


def todoist_list_tasks(
    token: str,
    filter_string: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """List tasks with optional filter.

    Enriches tasks with section_name and project_name for better context.
    """
    # Todoist API v1 evaluates the filter query language ("overdue", "today",
    # "7 days", ...) ONLY on the dedicated /tasks/filter endpoint. Passing
    # `filter` to /tasks is silently ignored - it returns ALL active tasks
    # (paginated), so "overdue" came back with 50 tasks including future-dated
    # recurring ones, which the briefing then mislabeled as overdue. Route any
    # filter through /tasks/filter with the `query` param; plain project
    # listing stays on /tasks.
    if filter_string:
        params: dict[str, Any] = {"query": filter_string}
        if project_id:
            params["project_id"] = project_id
        try:
            tasks = todoist_client.todoist_api_request("GET", "/tasks/filter", token, params=params)
        except Exception as e:
            if any(marker in str(e) for marker in _INVALID_FILTER_MARKERS):
                return _invalid_filter_result(filter_string)
            raise
    else:
        params = {}
        if project_id:
            params["project_id"] = project_id
        tasks = todoist_client.todoist_api_request("GET", "/tasks", token, params=params)
    if not isinstance(tasks, list):
        tasks = []

    # Cap the result count - every task is serialized into LLM context
    truncated_count = max(0, len(tasks) - Config.TODOIST_MAX_TASK_RESULTS)
    tasks = tasks[: Config.TODOIST_MAX_TASK_RESULTS]

    # Build section and project maps for enrichment
    section_map: dict[str, str] = {}
    project_map: dict[str, str] = {}

    # Collect unique section_ids and project_ids from tasks
    section_ids = {t.get("section_id") for t in tasks if t.get("section_id")}
    project_ids = {t.get("project_id") for t in tasks if t.get("project_id")}

    # Fetch all sections (more efficient than per-section requests)
    if section_ids:
        try:
            sections = todoist_client.todoist_api_request("GET", "/sections", token)
            if isinstance(sections, list):
                section_map = {
                    s["id"]: s["name"] for s in sections if s.get("id") and s.get("name")
                }
        except Exception as e:
            logger.warning("Failed to fetch sections for task enrichment", extra={"error": str(e)})

    # Fetch all projects for names
    if project_ids:
        try:
            projects = todoist_client.todoist_api_request("GET", "/projects", token)
            if isinstance(projects, list):
                project_map = {
                    p["id"]: p["name"] for p in projects if p.get("id") and p.get("name")
                }
        except Exception as e:
            logger.warning("Failed to fetch projects for task enrichment", extra={"error": str(e)})

    formatted_tasks = [format_task(task, section_map, project_map) for task in tasks]

    result: dict[str, Any] = {
        "action": "list_tasks",
        "filter": filter_string,
        "count": len(formatted_tasks),
        "tasks": formatted_tasks,
    }
    if truncated_count:
        result["truncated"] = f"{truncated_count} more tasks matched; narrow the filter to see them"
    return result


def todoist_get_task(token: str, task_id: str) -> dict[str, Any]:
    """Get a specific task by ID."""
    task_result = todoist_client.todoist_api_request("GET", f"/tasks/{task_id}", token)
    return {"action": "get_task", "task": task_result}


def todoist_add_task(
    token: str,
    content: str,
    description: str | None = None,
    project_id: str | None = None,
    section_id: str | None = None,
    due_string: str | None = None,
    due_date: str | None = None,
    priority: int | None = None,
    labels: list[str] | None = None,
    assignee_id: str | None = None,
) -> dict[str, Any]:
    """Create a new task."""
    task_data: dict[str, Any] = {"content": content}
    if description:
        task_data["description"] = description
    if project_id:
        task_data["project_id"] = project_id
    if section_id:
        task_data["section_id"] = section_id
    if due_string:
        task_data["due_string"] = due_string
    elif due_date:
        task_data["due_date"] = due_date
    if priority:
        task_data["priority"] = max(1, min(4, priority))
    if labels:
        task_data["labels"] = labels
    if assignee_id:
        task_data["assignee_id"] = assignee_id

    new_task = todoist_client.todoist_api_request("POST", "/tasks", token, data=task_data)
    return {"action": "add_task", "success": True, "task": new_task}


def todoist_update_task(
    token: str,
    task_id: str,
    content: str | None = None,
    description: str | None = None,
    due_string: str | None = None,
    due_date: str | None = None,
    priority: int | None = None,
    labels: list[str] | None = None,
    assignee_id: str | None = None,
) -> dict[str, Any]:
    """Update an existing task."""
    update_data: dict[str, Any] = {}
    if content:
        update_data["content"] = content
    if description is not None:  # Allow empty string to clear
        update_data["description"] = description
    if due_string:
        update_data["due_string"] = due_string
    elif due_date:
        update_data["due_date"] = due_date
    if priority:
        update_data["priority"] = max(1, min(4, priority))
    if labels is not None:  # Allow empty list to clear
        update_data["labels"] = labels
    if assignee_id is not None:  # Allow empty string to unassign
        update_data["assignee_id"] = assignee_id

    if not update_data:
        return {"error": "No fields to update provided"}

    updated_task = todoist_client.todoist_api_request(
        "POST", f"/tasks/{task_id}", token, data=update_data
    )
    return {"action": "update_task", "success": True, "task": updated_task}


def todoist_move_task(
    token: str,
    task_id: str,
    section_id: str | None = None,
    project_id: str | None = None,
    parent_id: str | None = None,
) -> dict[str, Any]:
    """Move a task to a different section, project, or make it a subtask.

    Uses the Sync API's item_move command since the REST API doesn't support moving tasks.

    Args:
        token: Todoist access token
        task_id: Task to move
        section_id: Target section (for moving within project)
        project_id: Target project (for moving between projects)
        parent_id: Parent task ID (for making subtask)

    Returns:
        Success status

    Note: Only ONE of section_id, project_id, or parent_id should be set.
    """
    # Build move command arguments
    args: dict[str, Any] = {"id": task_id}

    # Only one destination parameter should be set
    destinations = [section_id, project_id, parent_id]
    if sum(d is not None for d in destinations) != 1:
        return {
            "error": "Exactly one of section_id, project_id, or parent_id must be provided for move_task"
        }

    if section_id:
        args["section_id"] = section_id
    elif project_id:
        args["project_id"] = project_id
    elif parent_id:
        args["parent_id"] = parent_id

    # Execute move via Sync API
    commands = [{"type": "item_move", "args": args}]
    result = todoist_client.todoist_sync_request(token, commands)

    # Check if command succeeded
    sync_status = result.get("sync_status", {})
    command_uuid = commands[0]["uuid"]

    if command_uuid in sync_status and sync_status[command_uuid] == "ok":
        return {
            "action": "move_task",
            "success": True,
            "task_id": task_id,
            "message": "Task moved successfully",
        }
    else:
        error_info = sync_status.get(command_uuid, "Unknown error")
        return {"action": "move_task", "success": False, "error": error_info}


def todoist_complete_task(token: str, task_id: str) -> dict[str, Any]:
    """Mark a task as completed."""
    todoist_client.todoist_api_request("POST", f"/tasks/{task_id}/close", token)
    return {
        "action": "complete_task",
        "success": True,
        "task_id": task_id,
        "message": "Task marked as completed",
    }


def todoist_reopen_task(token: str, task_id: str) -> dict[str, Any]:
    """Reopen a completed task."""
    todoist_client.todoist_api_request("POST", f"/tasks/{task_id}/reopen", token)
    return {
        "action": "reopen_task",
        "success": True,
        "task_id": task_id,
        "message": "Task reopened",
    }


def todoist_delete_task(token: str, task_id: str) -> dict[str, Any]:
    """Delete a task permanently."""
    todoist_client.todoist_api_request("DELETE", f"/tasks/{task_id}", token)
    return {
        "action": "delete_task",
        "success": True,
        "task_id": task_id,
        "message": "Task deleted permanently",
    }
