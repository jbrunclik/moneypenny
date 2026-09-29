"""Todoist task management tool.

The tool validates arguments and dispatches; the HTTP layer lives in
todoist_client.py and the actions in todoist_tasks.py / todoist_projects.py.
"""

import json
from collections.abc import Callable
from typing import Any

from langchain_core.tools import tool

from src.agent.tools import todoist_client
from src.agent.tools import todoist_projects as projects
from src.agent.tools import todoist_tasks as tasks
from src.agent.tools.integration_status import not_connected_result
from src.agent.tools.permission_check import check_autonomous_permission
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


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


_Handler = Callable[[str, dict[str, Any]], dict[str, Any]]

# action -> (required argument names, handler(token, args)); validation messages
# read "<a> and <b> are required for <action> action"
_DISPATCH: dict[str, tuple[tuple[str, ...], _Handler]] = {
    "list_tasks": (
        (),
        lambda t, a: tasks.todoist_list_tasks(t, a["filter_string"], a["project_id"]),
    ),
    "list_projects": ((), lambda t, a: projects.todoist_list_projects(t)),
    "get_project": (("project_id",), lambda t, a: projects.todoist_get_project(t, a["project_id"])),
    "add_project": (
        ("project_name",),
        lambda t, a: projects.todoist_add_project(
            t,
            a["project_name"],
            a["color"],
            a["parent_project_id"],
            a["is_favorite"],
            a["view_style"],
        ),
    ),
    "update_project": (
        ("project_id",),
        lambda t, a: projects.todoist_update_project(
            t,
            a["project_id"],
            a["project_name"],
            a["color"],
            a["parent_project_id"],
            a["is_favorite"],
            a["view_style"],
        ),
    ),
    "delete_project": (
        ("project_id",),
        lambda t, a: projects.todoist_delete_project(t, a["project_id"]),
    ),
    "archive_project": (
        ("project_id",),
        lambda t, a: projects.todoist_archive_project(t, a["project_id"]),
    ),
    "unarchive_project": (
        ("project_id",),
        lambda t, a: projects.todoist_unarchive_project(t, a["project_id"]),
    ),
    "list_sections": (
        ("project_id",),
        lambda t, a: projects.todoist_list_sections(t, a["project_id"]),
    ),
    "get_section": (("section_id",), lambda t, a: projects.todoist_get_section(t, a["section_id"])),
    "add_section": (
        ("project_id", "section_name"),
        lambda t, a: projects.todoist_add_section(t, a["project_id"], a["section_name"]),
    ),
    "update_section": (
        ("section_id", "section_name"),
        lambda t, a: projects.todoist_update_section(t, a["section_id"], a["section_name"]),
    ),
    "delete_section": (
        ("section_id",),
        lambda t, a: projects.todoist_delete_section(t, a["section_id"]),
    ),
    "list_collaborators": (
        ("project_id",),
        lambda t, a: projects.todoist_list_collaborators(t, a["project_id"]),
    ),
    "get_task": (("task_id",), lambda t, a: tasks.todoist_get_task(t, a["task_id"])),
    "add_task": (
        ("content",),
        lambda t, a: tasks.todoist_add_task(
            t,
            a["content"],
            a["description"],
            a["project_id"],
            a["section_id"],
            a["due_string"],
            a["due_date"],
            a["priority"],
            a["labels"],
            a["assignee_id"],
        ),
    ),
    "update_task": (
        ("task_id",),
        lambda t, a: tasks.todoist_update_task(
            t,
            a["task_id"],
            a["content"],
            a["description"],
            a["due_string"],
            a["due_date"],
            a["priority"],
            a["labels"],
            a["assignee_id"],
        ),
    ),
    "move_task": (
        ("task_id",),
        lambda t, a: tasks.todoist_move_task(
            t, a["task_id"], a["section_id"], a["project_id"], a["parent_id"]
        ),
    ),
    "complete_task": (("task_id",), lambda t, a: tasks.todoist_complete_task(t, a["task_id"])),
    "reopen_task": (("task_id",), lambda t, a: tasks.todoist_reopen_task(t, a["task_id"])),
    "delete_task": (("task_id",), lambda t, a: tasks.todoist_delete_task(t, a["task_id"])),
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
    in settings. A "Todoist disconnected" / "Todoist not connected" result says
    which case applies - follow its message (warn the user and point them to
    Settings); never act as if you cannot use Todoist at all.

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
    token = todoist_client.get_todoist_token()
    if not token:
        return json.dumps(not_connected_result("todoist"))

    # Check permission for autonomous agents; entity ids enable
    # argument-level approval matching for destructive operations
    check_autonomous_permission(
        "todoist",
        {
            "operation": action,
            "task_id": task_id,
            "project_id": project_id,
            "section_id": section_id,
        },
    )

    args: dict[str, Any] = {
        "task_id": task_id,
        "content": content,
        "description": description,
        "project_id": project_id,
        "section_id": section_id,
        "due_string": due_string,
        "due_date": due_date,
        "priority": priority,
        "labels": labels,
        "assignee_id": assignee_id,
        "parent_id": parent_id,
        "filter_string": filter_string,
        "project_name": project_name,
        "parent_project_id": parent_project_id,
        "is_favorite": is_favorite,
        "view_style": view_style,
        "color": color,
        "section_name": section_name,
    }
    entry = _DISPATCH.get(action)
    if entry is None:
        return json.dumps(
            {
                "error": f"Unknown action: {action}",
                "available_actions": list(_TODOIST_ACTIONS),
            }
        )
    required, handler = entry
    missing = [name for name in required if not args[name]]
    if missing:
        verb = "is" if len(required) == 1 else "are"
        return json.dumps(
            {"error": f"{' and '.join(required)} {verb} required for {action} action"}
        )

    try:
        return json.dumps(handler(token, args))

    except todoist_client.TodoistTokenRejectedError:
        return json.dumps(not_connected_result("todoist", was_connected=True))
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
