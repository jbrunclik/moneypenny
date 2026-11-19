"""Todoist task management tool.

The tool validates arguments and dispatches; the HTTP layer lives in
todoist_client.py and the actions in todoist_tasks.py / todoist_projects.py.
"""

from collections.abc import Callable, Mapping
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel

from src.agent.tools import todoist_client
from src.agent.tools import todoist_completed as completed
from src.agent.tools import todoist_projects as projects
from src.agent.tools import todoist_tasks as tasks
from src.agent.tools.errors import action_result, tool_error
from src.agent.tools.integration_status import not_connected_result
from src.agent.tools.permission_check import call_arguments, check_autonomous_permission
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
    "add_tasks",
    "list_completed",
}


# One task of an add_tasks call: add_task's common fields, without field
# descriptions - they mirror the tool's own Args (documented once there), and
# the schema is re-sent on every model call that binds the tool. A description
# or assignee goes through add_task / update_task.
class NewTask(BaseModel):
    content: str
    due_string: str | None = None
    due_date: str | None = None
    priority: int | None = None
    labels: list[str] | None = None
    project_id: str | None = None
    section_id: str | None = None


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
    "add_tasks": (
        ("tasks",),
        lambda t, a: tasks.todoist_add_tasks(t, a["tasks"], a["project_id"], a["section_id"]),
    ),
    "list_completed": (
        (),
        lambda t, a: completed.todoist_list_completed(t, a["since"], a["until"], a["project_id"]),
    ),
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
    tasks: list[NewTask] | None = None,
    since: str | None = None,
    until: str | None = None,
) -> str:
    """Manage the user's Todoist tasks, projects, and sections.

    Needs the user's Todoist connected in Settings. A "Todoist disconnected" /
    "Todoist not connected" result says which case applies - follow its message
    (warn the user, point them to Settings); never act as if you cannot use Todoist.

    Actions (required args in parentheses):
    - Tasks: list_tasks (optional filter_string; none = all active tasks), get_task,
      complete_task, reopen_task, delete_task (task_id); add_task (content; optional
      description, project_id, section_id, due_string/due_date, priority, labels,
      assignee_id); update_task (task_id + fields to change; assignee_id="" unassigns);
      move_task (task_id + exactly ONE of section_id, project_id, parent_id);
      add_tasks (tasks: 2-25 tasks in one call, each content + optional due, priority,
      labels, placement; the call's project_id/section_id are the default);
      list_completed (optional since/until YYYY-MM-DD, default the last 7 days;
      optional project_id).
    - Projects: list_projects; get_project, delete_project, archive_project,
      unarchive_project (project_id); add_project (project_name; optional color,
      view_style, parent_project_id, is_favorite); update_project (project_id + fields).
    - Sections: list_sections, add_section (project_id; add also section_name);
      get_section, delete_section (section_id); update_section (section_id, section_name).
    - list_collaborators (project_id): IDs for assignee_id.

    filter_string: Todoist filter syntax - "today", "overdue", "tomorrow", "7 days",
    "no date", "p1", "#Project", "@label", "assigned to: me"; combine with & and |.
    Priority: 4 = urgent (highest) ... 1 = normal; the filter "p1" means priority 4.

    Args:
        action: One of the actions above
        task_id: Task ID
        content: Task title
        description: Task description
        project_id: Project ID (task placement, sections, collaborators; move_task destination)
        section_id: Section ID (task placement; move_task destination)
        due_string: Natural language due date, e.g. "tomorrow at 3pm"
        due_date: Due date as YYYY-MM-DD
        priority: 1-4, 4 is highest
        labels: Label names
        assignee_id: Collaborator ID (from list_collaborators); "" unassigns
        parent_id: move_task: parent task ID to make the task a subtask
        filter_string: Filter for list_tasks
        project_name: Project name (create/rename)
        parent_project_id: Parent project (create/move a project under another)
        is_favorite: Show the project in favorites
        view_style: "list" or "board"
        color: Todoist color name
        section_name: Section name (create/rename)
        tasks: add_tasks entries
        since: list_completed from (YYYY-MM-DD)
        until: list_completed to, inclusive (YYYY-MM-DD)
    """
    logger.info(
        "todoist called",
        extra={"action": action, "task_id": task_id, "task_count": len(tasks or [])},
    )

    # Check if user has connected Todoist
    token = todoist_client.get_todoist_token()
    if not token:
        return not_connected_result("todoist")

    # The gate sees the whole call: in a run, a change it may not make alone
    # files that exact call's card and pauses; in chat a delete or archive
    # waits on the turn's card (the result says so)
    # The gate stores the call for its card: tasks as plain JSON, not models
    task_entries = [task.model_dump(exclude_none=True) for task in tasks or []]
    scope = {**locals(), "tasks": task_entries or None}
    if held := check_autonomous_permission("todoist", call_arguments(todoist, scope)):
        return held

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
        "tasks": task_entries,
        "since": since,
        "until": until,
    }
    return _run_todoist_action(action, token, args)


def _run_todoist_action(action: str, token: str, args: dict[str, Any]) -> str:
    """Validate the action's required arguments, run it and shape the result."""
    entry = _DISPATCH.get(action)
    if entry is None:
        return tool_error(f"Unknown action: {action}", available_actions=list(_TODOIST_ACTIONS))
    required, handler = entry
    missing = [name for name in required if not args[name]]
    if missing:
        verb = "is" if len(required) == 1 else "are"
        return tool_error(f"{' and '.join(required)} {verb} required for {action} action")

    try:
        return action_result(handler(token, args))

    except todoist_client.TodoistTokenRejectedError:
        return not_connected_result("todoist", was_connected=True)
    except Exception as e:
        logger.exception(
            "Todoist tool error",
            extra={"action": action, "error": str(e)},
        )
        return tool_error(str(e), action=action)


def is_todoist_available() -> bool:
    """Check if Todoist integration is configured."""
    return bool(Config.TODOIST_CLIENT_ID and Config.TODOIST_CLIENT_SECRET)


# Where a gated operation's item is read back, and its name field
_ITEM_PATHS: dict[str, tuple[str, str, str]] = {
    "delete_task": ("/tasks/", "task_id", "content"),
    "delete_project": ("/projects/", "project_id", "name"),
    "archive_project": ("/projects/", "project_id", "name"),
    "delete_section": ("/sections/", "section_id", "name"),
}


def item_name(args: Mapping[str, object]) -> str | None:
    """The name of the task, project or section a delete or archive changes
    (for its card, src/agent/chat_changes.py)."""
    path = _ITEM_PATHS.get(str(args.get("action") or ""))
    token = todoist_client.get_todoist_token()
    if path is None or not token or not args.get(path[1]):
        return None
    found = todoist_client.todoist_api_request("GET", f"{path[0]}{args[path[1]]}", token)
    if not isinstance(found, dict):
        return None
    return str(found.get(path[2]) or "") or None
