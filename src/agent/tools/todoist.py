"""Todoist task management tool."""

import json
from typing import Any

from langchain_core.tools import tool

from src.agent.tools.context import get_conversation_context
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _get_todoist_token() -> str | None:
    """Get the current user's Todoist access token.

    Returns None if user is not connected to Todoist.
    """
    _, user_id = get_conversation_context()
    if not user_id:
        return None

    from src.db.models import db

    user = db.get_user_by_id(user_id)
    if not user:
        return None

    return user.todoist_access_token


def _todoist_api_request(
    method: str,
    endpoint: str,
    token: str,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    """Make a request to the Todoist REST API.

    Args:
        method: HTTP method (GET, POST, DELETE)
        endpoint: API endpoint path (e.g., "/tasks")
        token: Todoist access token
        data: Request body for POST requests
        params: Query parameters

    Returns:
        JSON response or None for DELETE requests

    Raises:
        Exception: On API errors
    """
    import requests

    url = f"{Config.TODOIST_API_BASE_URL}{endpoint}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        if method == "GET":
            response = requests.get(
                url, headers=headers, params=params, timeout=Config.TODOIST_API_TIMEOUT
            )
        elif method == "POST":
            headers["Content-Type"] = "application/json"
            response = requests.post(
                url, headers=headers, json=data, timeout=Config.TODOIST_API_TIMEOUT
            )
        elif method == "DELETE":
            response = requests.delete(url, headers=headers, timeout=Config.TODOIST_API_TIMEOUT)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        if response.status_code == 204:  # No content (successful DELETE)
            return None

        if response.status_code >= 400:
            error_msg = response.text
            logger.warning(
                "Todoist API error",
                extra={
                    "status_code": response.status_code,
                    "error": error_msg,
                    "endpoint": endpoint,
                },
            )
            # Handle auth errors with clear reconnection message
            if response.status_code in (401, 403):
                raise Exception(
                    "Todoist access has been revoked or expired. "
                    "Please reconnect your Todoist account in Settings."
                )
            raise Exception(f"Todoist API error ({response.status_code}): {error_msg}")

        result: dict[str, Any] | list[dict[str, Any]] = response.json()
        return result

    except requests.RequestException as e:
        logger.error("Todoist API request failed", extra={"error": str(e), "endpoint": endpoint})
        raise Exception(f"Failed to connect to Todoist: {e}") from e


def _todoist_sync_request(
    token: str,
    commands: list[dict[str, Any]],
) -> dict[str, Any]:
    """Make a request to the Todoist Sync API.

    The Sync API is used for operations not supported by the REST API,
    such as moving tasks between sections.

    Args:
        token: Todoist access token
        commands: List of command objects (e.g., [{"type": "item_move", "uuid": ..., "args": {...}}])

    Returns:
        Sync response with sync_status for each command

    Raises:
        Exception: On API errors
    """
    import json as json_module
    import uuid

    import requests

    url = "https://api.todoist.com/sync/v9/sync"
    headers = {"Authorization": f"Bearer {token}"}

    # Add UUIDs to commands if not present
    for cmd in commands:
        if "uuid" not in cmd:
            cmd["uuid"] = str(uuid.uuid4())

    # Sync API expects form-encoded data, not JSON
    data = {"commands": json_module.dumps(commands)}

    try:
        response = requests.post(
            url, headers=headers, data=data, timeout=Config.TODOIST_API_TIMEOUT
        )

        if response.status_code >= 400:
            error_msg = response.text
            logger.warning(
                "Todoist Sync API error",
                extra={"status_code": response.status_code, "error": error_msg},
            )
            if response.status_code in (401, 403):
                raise Exception(
                    "Todoist access has been revoked or expired. "
                    "Please reconnect your Todoist account in Settings."
                )
            raise Exception(f"Todoist Sync API error ({response.status_code}): {error_msg}")

        result: dict[str, Any] = response.json()
        return result

    except requests.RequestException as e:
        logger.error("Todoist Sync API request failed", extra={"error": str(e)})
        raise Exception(f"Failed to connect to Todoist Sync API: {e}") from e


# ============================================================================
# Todoist Action Handlers
# ============================================================================


def _format_task(
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
        "is_completed": task.get("is_completed", False),
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
    # Assignment information
    if task.get("assignee_id"):
        formatted["assignee_id"] = task["assignee_id"]
    if task.get("assigner_id"):
        formatted["assigner_id"] = task["assigner_id"]
    # Duration/time estimate
    if task.get("duration"):
        duration = task["duration"]
        formatted["duration"] = f"{duration.get('amount', 0)} {duration.get('unit', 'minute')}"
    # Comment count (useful context)
    if task.get("comment_count", 0) > 0:
        formatted["comment_count"] = task["comment_count"]
    # Direct URL to task in Todoist
    if task.get("url"):
        formatted["url"] = task["url"]
    return formatted


def _todoist_list_tasks(
    token: str,
    filter_string: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """List tasks with optional filter.

    Enriches tasks with section_name and project_name for better context.
    """
    params: dict[str, Any] = {}
    if filter_string:
        params["filter"] = filter_string
    if project_id:
        params["project_id"] = project_id

    tasks = _todoist_api_request("GET", "/tasks", token, params=params)
    if not isinstance(tasks, list):
        tasks = []

    # Build section and project maps for enrichment
    section_map: dict[str, str] = {}
    project_map: dict[str, str] = {}

    # Collect unique section_ids and project_ids from tasks
    section_ids = {t.get("section_id") for t in tasks if t.get("section_id")}
    project_ids = {t.get("project_id") for t in tasks if t.get("project_id")}

    # Fetch all sections (more efficient than per-section requests)
    if section_ids:
        try:
            sections = _todoist_api_request("GET", "/sections", token)
            if isinstance(sections, list):
                section_map = {
                    s["id"]: s["name"] for s in sections if s.get("id") and s.get("name")
                }
        except Exception as e:
            logger.warning("Failed to fetch sections for task enrichment", extra={"error": str(e)})

    # Fetch all projects for names
    if project_ids:
        try:
            projects = _todoist_api_request("GET", "/projects", token)
            if isinstance(projects, list):
                project_map = {
                    p["id"]: p["name"] for p in projects if p.get("id") and p.get("name")
                }
        except Exception as e:
            logger.warning("Failed to fetch projects for task enrichment", extra={"error": str(e)})

    formatted_tasks = [_format_task(task, section_map, project_map) for task in tasks]

    return {
        "action": "list_tasks",
        "filter": filter_string,
        "count": len(formatted_tasks),
        "tasks": formatted_tasks,
    }


def _todoist_list_projects(token: str) -> dict[str, Any]:
    """List all projects with their full metadata."""
    projects = _todoist_api_request("GET", "/projects", token)
    if not isinstance(projects, list):
        projects = []

    formatted_projects = []
    for p in projects:
        proj: dict[str, Any] = {
            "id": p["id"],
            "name": p["name"],
            "color": p.get("color"),
            "is_favorite": p.get("is_favorite", False),
        }
        # Include parent_id for nested project hierarchy
        if p.get("parent_id"):
            proj["parent_id"] = p["parent_id"]
        # View style (list or board) - useful for understanding project structure
        if p.get("view_style"):
            proj["view_style"] = p["view_style"]
        # Mark the inbox project for special handling
        if p.get("is_inbox_project"):
            proj["is_inbox_project"] = True
        # Shared/collaborative projects
        if p.get("is_shared"):
            proj["is_shared"] = True
        formatted_projects.append(proj)

    return {
        "action": "list_projects",
        "count": len(formatted_projects),
        "projects": formatted_projects,
    }


def _todoist_get_project(token: str, project_id: str) -> dict[str, Any]:
    """Fetch a single project by ID."""
    project = _todoist_api_request("GET", f"/projects/{project_id}", token)
    if not isinstance(project, dict):
        raise Exception("Failed to fetch project")
    return {"action": "get_project", "project": project}


def _todoist_add_project(
    token: str,
    project_name: str,
    color: str | None = None,
    parent_project_id: str | None = None,
    is_favorite: bool | None = None,
    view_style: str | None = None,
) -> dict[str, Any]:
    """Create a new Todoist project."""
    data: dict[str, Any] = {"name": project_name}
    if color:
        data["color"] = color
    if parent_project_id:
        data["parent_id"] = parent_project_id
    if is_favorite is not None:
        data["is_favorite"] = is_favorite
    if view_style:
        data["view_style"] = view_style

    project = _todoist_api_request("POST", "/projects", token, data=data)
    if not isinstance(project, dict):
        raise Exception("Failed to create project")
    return {"action": "add_project", "success": True, "project": project}


def _todoist_update_project(
    token: str,
    project_id: str,
    project_name: str | None = None,
    color: str | None = None,
    parent_project_id: str | None = None,
    is_favorite: bool | None = None,
    view_style: str | None = None,
) -> dict[str, Any]:
    """Update project metadata (name, color, favorite state, etc.)."""
    data: dict[str, Any] = {}
    if project_name:
        data["name"] = project_name
    if color:
        data["color"] = color
    if parent_project_id is not None:
        data["parent_id"] = parent_project_id
    if is_favorite is not None:
        data["is_favorite"] = is_favorite
    if view_style:
        data["view_style"] = view_style

    if not data:
        return {"error": "No project fields provided for update"}

    project = _todoist_api_request("POST", f"/projects/{project_id}", token, data=data)
    if not isinstance(project, dict):
        raise Exception("Failed to update project")
    return {"action": "update_project", "success": True, "project": project}


def _todoist_delete_project(token: str, project_id: str) -> dict[str, Any]:
    """Delete a project permanently."""
    _todoist_api_request("DELETE", f"/projects/{project_id}", token)
    return {
        "action": "delete_project",
        "success": True,
        "project_id": project_id,
        "message": "Project deleted",
    }


def _todoist_archive_project(token: str, project_id: str) -> dict[str, Any]:
    """Archive a project to hide it from active view."""
    _todoist_api_request("POST", f"/projects/{project_id}/archive", token)
    return {
        "action": "archive_project",
        "success": True,
        "project_id": project_id,
        "message": "Project archived",
    }


def _todoist_unarchive_project(token: str, project_id: str) -> dict[str, Any]:
    """Bring an archived project back."""
    _todoist_api_request("POST", f"/projects/{project_id}/unarchive", token)
    return {
        "action": "unarchive_project",
        "success": True,
        "project_id": project_id,
        "message": "Project unarchived",
    }


def _todoist_list_sections(token: str, project_id: str) -> dict[str, Any]:
    """List all sections for a specific project.

    Sections help organize tasks within a project (e.g., "To Do", "In Progress", "Done").
    """
    sections = _todoist_api_request("GET", "/sections", token, params={"project_id": project_id})
    if not isinstance(sections, list):
        sections = []

    formatted_sections = [
        {
            "id": s["id"],
            "name": s["name"],
            "order": s.get("order", 0),
        }
        for s in sections
    ]

    # Sort by order for logical display
    formatted_sections.sort(key=lambda s: s["order"])

    return {
        "action": "list_sections",
        "project_id": project_id,
        "count": len(formatted_sections),
        "sections": formatted_sections,
    }


def _todoist_get_section(token: str, section_id: str) -> dict[str, Any]:
    """Fetch a section by ID."""
    section = _todoist_api_request("GET", f"/sections/{section_id}", token)
    if not isinstance(section, dict):
        raise Exception("Failed to fetch section")
    return {"action": "get_section", "section": section}


def _todoist_add_section(token: str, project_id: str, section_name: str) -> dict[str, Any]:
    """Create a new section inside a project."""
    data = {"project_id": project_id, "name": section_name}
    section = _todoist_api_request("POST", "/sections", token, data=data)
    if not isinstance(section, dict):
        raise Exception("Failed to create section")
    return {"action": "add_section", "success": True, "section": section}


def _todoist_update_section(token: str, section_id: str, section_name: str) -> dict[str, Any]:
    """Rename an existing section."""
    data = {"name": section_name}
    section = _todoist_api_request("POST", f"/sections/{section_id}", token, data=data)
    if not isinstance(section, dict):
        raise Exception("Failed to update section")
    return {"action": "update_section", "success": True, "section": section}


def _todoist_delete_section(token: str, section_id: str) -> dict[str, Any]:
    """Delete a section from a project."""
    _todoist_api_request("DELETE", f"/sections/{section_id}", token)
    return {
        "action": "delete_section",
        "success": True,
        "section_id": section_id,
        "message": "Section deleted",
    }


def _todoist_list_collaborators(token: str, project_id: str) -> dict[str, Any]:
    """List all collaborators for a shared project.

    Returns information about who can be assigned tasks in the project.
    """
    collaborators = _todoist_api_request("GET", f"/projects/{project_id}/collaborators", token)
    if not isinstance(collaborators, list):
        collaborators = []

    formatted_collaborators = [
        {
            "id": c["id"],
            "name": c["name"],
            "email": c["email"],
        }
        for c in collaborators
    ]

    return {
        "action": "list_collaborators",
        "project_id": project_id,
        "count": len(formatted_collaborators),
        "collaborators": formatted_collaborators,
    }


def _todoist_get_task(token: str, task_id: str) -> dict[str, Any]:
    """Get a specific task by ID."""
    task_result = _todoist_api_request("GET", f"/tasks/{task_id}", token)
    return {"action": "get_task", "task": task_result}


def _todoist_add_task(
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

    new_task = _todoist_api_request("POST", "/tasks", token, data=task_data)
    return {"action": "add_task", "success": True, "task": new_task}


def _todoist_update_task(
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

    updated_task = _todoist_api_request("POST", f"/tasks/{task_id}", token, data=update_data)
    return {"action": "update_task", "success": True, "task": updated_task}


def _todoist_move_task(
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
    result = _todoist_sync_request(token, commands)

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


def _todoist_complete_task(token: str, task_id: str) -> dict[str, Any]:
    """Mark a task as completed."""
    _todoist_api_request("POST", f"/tasks/{task_id}/close", token)
    return {
        "action": "complete_task",
        "success": True,
        "task_id": task_id,
        "message": "Task marked as completed",
    }


def _todoist_reopen_task(token: str, task_id: str) -> dict[str, Any]:
    """Reopen a completed task."""
    _todoist_api_request("POST", f"/tasks/{task_id}/reopen", token)
    return {
        "action": "reopen_task",
        "success": True,
        "task_id": task_id,
        "message": "Task reopened",
    }


def _todoist_delete_task(token: str, task_id: str) -> dict[str, Any]:
    """Delete a task permanently."""
    _todoist_api_request("DELETE", f"/tasks/{task_id}", token)
    return {
        "action": "delete_task",
        "success": True,
        "task_id": task_id,
        "message": "Task deleted permanently",
    }


# Map of action names for validation
_TODOIST_ACTIONS = {
    "list_tasks",
    "list_projects",
    "get_project",
    "add_project",
    "update_project",
    "delete_project",
    "archive_project",
    "unarchive_project",
    "list_sections",
    "get_section",
    "add_section",
    "update_section",
    "delete_section",
    "list_collaborators",
    "get_task",
    "add_task",
    "update_task",
    "move_task",
    "complete_task",
    "reopen_task",
    "delete_task",
}


@tool
def todoist(
    action: str,
    task_id: str | None = None,
    content: str | None = None,
    description: str | None = None,
    project_id: str | None = None,
    section_id: str | None = None,
    due_string: str | None = None,
    due_date: str | None = None,
    priority: int | None = None,
    labels: list[str] | None = None,
    assignee_id: str | None = None,
    parent_id: str | None = None,
    filter_string: str | None = None,
    project_name: str | None = None,
    parent_project_id: str | None = None,
    is_favorite: bool | None = None,
    view_style: str | None = None,
    color: str | None = None,
    section_name: str | None = None,
) -> str:
    """Manage the user's Todoist tasks, projects, and sections.

    IMPORTANT: This tool only works if the user has connected their Todoist account
    in settings. If you get "Todoist not connected", ask the user to connect
    their Todoist account in settings first.

    Actions available:
    - "list_tasks": List tasks. Use filter_string for Todoist filter syntax (e.g., "today",
      "overdue", "p1", "tomorrow", "#Work", "@urgent"). Without filter, returns all active tasks.
      Tasks include section_id and section_name for context, and assignee_id if assigned.
    - "list_projects": List all projects.
    - "get_project": Get a specific project by project_id.
    - "add_project": Create a new project. Requires 'project_name'. Optional: color, view_style ("list" or
      "board"), parent_project_id, is_favorite.
    - "update_project": Update an existing project. Requires 'project_id' and at least one field to update
      (project_name, color, view_style, parent_project_id, is_favorite).
    - "delete_project": Delete a project permanently. Requires 'project_id'.
    - "archive_project" / "unarchive_project": Archive or unarchive a project. Requires 'project_id'.
    - "list_sections": List sections for a project. Requires 'project_id'.
    - "get_section": Get a section by section_id.
    - "add_section": Create a new section in a project. Requires 'project_id' and 'section_name'.
    - "update_section": Rename an existing section. Requires 'section_id' and new 'section_name'.
    - "delete_section": Delete a section. Requires 'section_id'.
    - "list_collaborators": List all collaborators for a shared project. Requires 'project_id'.
      Returns collaborator IDs that can be used with assignee_id when creating/updating tasks.
    - "get_task": Get a specific task by task_id.
    - "add_task": Create a new task. Requires 'content' (task title).
      Optional: description, project_id, section_id, due_string (natural language like "tomorrow at 3pm"),
      due_date (YYYY-MM-DD), priority (1-4, where 4 is highest), labels (list of label names),
      assignee_id (ID of collaborator to assign task to).
    - "update_task": Update an existing task. Requires 'task_id'.
      Optional: content, description, due_string, due_date, priority, labels, assignee_id.
      Use assignee_id="" (empty string) to unassign a task.
    - "move_task": Move a task to a different section, project, or make it a subtask. Requires 'task_id' and exactly
      ONE of: section_id (move to section within same project), project_id (move to different project), or parent_id
      (make it a subtask of another task).
    - "complete_task": Mark a task as completed. Requires 'task_id'.
    - "reopen_task": Reopen a completed task. Requires 'task_id'.
    - "delete_task": Delete a task permanently. Requires 'task_id'.

    Todoist filter syntax examples:
    - "today" - Tasks due today
    - "overdue" - Overdue tasks
    - "tomorrow" - Tasks due tomorrow
    - "7 days" or "next 7 days" - Tasks due in the next 7 days
    - "no date" - Tasks without a due date
    - "p1" - Priority 1 (highest) tasks
    - "#ProjectName" - Tasks in a specific project
    - "@LabelName" - Tasks with a specific label
    - "assigned to: me" - Tasks assigned to the user
    - Combine with & (and) or | (or): "today & p1", "overdue | today"

    Priority levels:
    - 1 = Normal (lowest)
    - 2 = Medium
    - 3 = High
    - 4 = Urgent (highest, shown in red)

    Args:
        action: The action to perform (task/project/section lifecycle actions listed above)
        task_id: Task ID for task operations
        content: Task title/content for add_task or update_task
        description: Task description for add_task or update_task
        project_id: Project context for listing sections, adding sections, task placement, or listing collaborators.
            For move_task: destination project ID (only one of section_id/project_id/parent_id should be provided).
        section_id: Section ID for section operations or task placement.
            For move_task: destination section ID (only one of section_id/project_id/parent_id should be provided).
        due_string: Natural language due date (e.g., "tomorrow at 3pm", "next Monday")
        due_date: Due date in YYYY-MM-DD format
        priority: Priority level 1-4 (4 is highest)
        labels: List of label names to apply
        assignee_id: Collaborator ID to assign task to (use list_collaborators to get IDs). Use empty string to unassign.
        parent_id: For move_task: parent task ID to make the task a subtask
            (only one of section_id/project_id/parent_id should be provided).
        filter_string: Todoist filter syntax for list_tasks
        project_name: Name used when creating or renaming a project
        parent_project_id: Optional parent project when creating/moving a project under another
        is_favorite: Whether the project should appear in favorites
        view_style: Project view style ("list" or "board")
        color: Project color name supported by Todoist
        section_name: Name for section create/update actions

    Returns:
        JSON string with the result
    """
    logger.info("todoist called", extra={"action": action, "task_id": task_id})

    # Check if user has connected Todoist
    token = _get_todoist_token()
    if not token:
        return json.dumps(
            {
                "error": "Todoist not connected",
                "message": "Please ask the user to connect their Todoist account in settings first.",
            }
        )

    try:
        # Dispatch to the appropriate action handler
        if action == "list_tasks":
            result = _todoist_list_tasks(token, filter_string, project_id)

        elif action == "list_projects":
            result = _todoist_list_projects(token)

        elif action == "get_project":
            if not project_id:
                return json.dumps({"error": "project_id is required for get_project action"})
            result = _todoist_get_project(token, project_id)

        elif action == "add_project":
            if not project_name:
                return json.dumps({"error": "project_name is required for add_project action"})
            result = _todoist_add_project(
                token,
                project_name,
                color,
                parent_project_id,
                is_favorite,
                view_style,
            )

        elif action == "update_project":
            if not project_id:
                return json.dumps({"error": "project_id is required for update_project action"})
            result = _todoist_update_project(
                token,
                project_id,
                project_name,
                color,
                parent_project_id,
                is_favorite,
                view_style,
            )

        elif action == "delete_project":
            if not project_id:
                return json.dumps({"error": "project_id is required for delete_project action"})
            result = _todoist_delete_project(token, project_id)

        elif action == "archive_project":
            if not project_id:
                return json.dumps({"error": "project_id is required for archive_project action"})
            result = _todoist_archive_project(token, project_id)

        elif action == "unarchive_project":
            if not project_id:
                return json.dumps({"error": "project_id is required for unarchive_project action"})
            result = _todoist_unarchive_project(token, project_id)

        elif action == "list_sections":
            if not project_id:
                return json.dumps({"error": "project_id is required for list_sections action"})
            result = _todoist_list_sections(token, project_id)

        elif action == "get_section":
            if not section_id:
                return json.dumps({"error": "section_id is required for get_section action"})
            result = _todoist_get_section(token, section_id)

        elif action == "add_section":
            if not project_id or not section_name:
                return json.dumps(
                    {
                        "error": "project_id and section_name are required for add_section action",
                    }
                )
            result = _todoist_add_section(token, project_id, section_name)

        elif action == "update_section":
            if not section_id or not section_name:
                return json.dumps(
                    {
                        "error": "section_id and section_name are required for update_section action",
                    }
                )
            result = _todoist_update_section(token, section_id, section_name)

        elif action == "delete_section":
            if not section_id:
                return json.dumps({"error": "section_id is required for delete_section action"})
            result = _todoist_delete_section(token, section_id)

        elif action == "list_collaborators":
            if not project_id:
                return json.dumps({"error": "project_id is required for list_collaborators action"})
            result = _todoist_list_collaborators(token, project_id)

        elif action == "get_task":
            if not task_id:
                return json.dumps({"error": "task_id is required for get_task action"})
            result = _todoist_get_task(token, task_id)

        elif action == "add_task":
            if not content:
                return json.dumps({"error": "content is required for add_task action"})
            result = _todoist_add_task(
                token,
                content,
                description,
                project_id,
                section_id,
                due_string,
                due_date,
                priority,
                labels,
                assignee_id,
            )

        elif action == "update_task":
            if not task_id:
                return json.dumps({"error": "task_id is required for update_task action"})
            result = _todoist_update_task(
                token,
                task_id,
                content,
                description,
                due_string,
                due_date,
                priority,
                labels,
                assignee_id,
            )

        elif action == "move_task":
            if not task_id:
                return json.dumps({"error": "task_id is required for move_task action"})
            result = _todoist_move_task(token, task_id, section_id, project_id, parent_id)

        elif action == "complete_task":
            if not task_id:
                return json.dumps({"error": "task_id is required for complete_task action"})
            result = _todoist_complete_task(token, task_id)

        elif action == "reopen_task":
            if not task_id:
                return json.dumps({"error": "task_id is required for reopen_task action"})
            result = _todoist_reopen_task(token, task_id)

        elif action == "delete_task":
            if not task_id:
                return json.dumps({"error": "task_id is required for delete_task action"})
            result = _todoist_delete_task(token, task_id)

        else:
            return json.dumps(
                {
                    "error": f"Unknown action: {action}",
                    "available_actions": list(_TODOIST_ACTIONS),
                }
            )

        return json.dumps(result)

    except Exception as e:
        logger.error(
            "Todoist tool error",
            extra={"action": action, "error": str(e)},
            exc_info=True,
        )
        return json.dumps({"error": str(e), "action": action})


def is_todoist_available() -> bool:
    """Check if Todoist integration is configured."""
    return bool(Config.TODOIST_CLIENT_ID and Config.TODOIST_CLIENT_SECRET)
