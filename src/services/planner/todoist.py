"""Todoist tasks for the planner dashboard: the next 7 days and overdue."""

import json
from typing import Any

import httpx

from src.config import Config
from src.services.planner.dates import parse_date
from src.services.planner.models import PlannerTask
from src.utils.clock import local_today
from src.utils.logging import get_logger

logger = get_logger(__name__)


def format_task(
    task: dict[str, Any],
    section_map: dict[str, str] | None = None,
    project_map: dict[str, str] | None = None,
) -> PlannerTask:
    """Convert a raw Todoist task to a PlannerTask."""
    due_date = None
    due_string = None
    is_recurring = False

    if task.get("due"):
        due = task["due"]
        due_date = due.get("date")
        due_string = due.get("string")
        is_recurring = due.get("is_recurring", False)

    project_name = None
    if task.get("project_id") and project_map:
        project_name = project_map.get(task["project_id"])

    section_name = None
    if task.get("section_id") and section_map:
        section_name = section_map.get(task["section_id"])

    return PlannerTask(
        id=task["id"],
        content=task["content"],
        description=task.get("description", ""),
        due_date=due_date,
        due_string=due_string,
        priority=task.get("priority", 1),
        project_name=project_name,
        section_name=section_name,
        labels=task.get("labels", []),
        is_recurring=is_recurring,
        url=task.get("url"),
    )


def _get(endpoint: str, headers: dict[str, str], **kwargs: Any) -> httpx.Response:
    return httpx.get(
        f"{Config.TODOIST_API_BASE_URL}/{endpoint}",
        headers=headers,
        timeout=Config.TODOIST_API_TIMEOUT_SECONDS,
        follow_redirects=True,
        **kwargs,
    )


def _response_error(response: httpx.Response) -> str | None:
    """The dashboard message for a failed tasks request, or None when it succeeded."""
    if response.status_code in (401, 403, 410):
        return "Todoist access has expired. Please reconnect in Settings."
    if response.status_code >= 400:
        logger.warning(
            "Todoist API error",
            extra={"status_code": response.status_code, "error": response.text},
        )
        return f"Todoist API error ({response.status_code})"
    return None


def _tasks_from_payload(tasks_data: Any) -> Any:
    """API v1 wraps list responses in {"results": [...]}; older ones are bare lists."""
    if isinstance(tasks_data, dict) and "results" in tasks_data:
        return tasks_data["results"]
    if isinstance(tasks_data, list):
        return tasks_data
    return []


def _fetch_name_map(endpoint: str, headers: dict[str, str], failure: str) -> dict[str, str]:
    """Map section or project ids to names; enrichment only, so failures give {}."""
    try:
        response = _get(endpoint, headers)
        if response.status_code != 200:
            return {}
        data = response.json()
        # API v1 wraps in {"results": [...]}
        items = data.get("results", []) if isinstance(data, dict) else data
        if isinstance(items, list):
            return {item["id"]: item["name"] for item in items if item.get("id")}
    except Exception as e:  # section/project names are optional enrichment
        logger.warning(
            failure,
            extra={"error": str(e)},
            exc_info=True,
        )
    return {}


def _enrichment_maps(
    tasks: list[dict[str, Any]], headers: dict[str, str]
) -> tuple[dict[str, str], dict[str, str]]:
    """(section_map, project_map), each fetched only when some task uses it."""
    section_map: dict[str, str] = {}
    project_map: dict[str, str] = {}
    if any(t.get("section_id") for t in tasks):
        section_map = _fetch_name_map("sections", headers, "Failed to fetch sections for dashboard")
    if any(t.get("project_id") for t in tasks):
        project_map = _fetch_name_map("projects", headers, "Failed to fetch projects for dashboard")
    return section_map, project_map


def _split_overdue(
    tasks: list[dict[str, Any]],
    section_map: dict[str, str],
    project_map: dict[str, str],
) -> tuple[list[PlannerTask], list[PlannerTask]]:
    """Split tasks into (upcoming, overdue); tasks without a due date are upcoming."""
    today = local_today()
    upcoming: list[PlannerTask] = []
    overdue: list[PlannerTask] = []
    for task in tasks:
        planner_task = format_task(task, section_map, project_map)
        task_date = parse_date(planner_task.due_date) if planner_task.due_date else None
        if task_date and task_date < today:
            overdue.append(planner_task)
        else:
            upcoming.append(planner_task)
    return upcoming, overdue


def fetch_todoist_dashboard_data(
    access_token: str,
) -> tuple[list[PlannerTask], list[PlannerTask], str | None]:
    """Fetch Todoist tasks for the next 7 days and overdue tasks.

    Args:
        access_token: The user's Todoist access token

    Returns:
        Tuple of (tasks_by_due_date, overdue_tasks, error_message)
        tasks_by_due_date: Tasks due in the next 7 days
        overdue_tasks: Tasks that are overdue
        error_message: Error message if any, None otherwise
    """
    logger.debug("Fetching Todoist dashboard data")
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        # One request gets both the next 7 days and overdue
        response = _get("tasks", headers, params={"filter": "7 days | overdue"})
        error = _response_error(response)
        if error:
            return [], [], error

        tasks = _tasks_from_payload(response.json())
        section_map, project_map = _enrichment_maps(tasks, headers)
        upcoming, overdue = _split_overdue(tasks, section_map, project_map)
        logger.debug(
            "Todoist dashboard data fetched",
            extra={"tasks_7_days": len(upcoming), "overdue": len(overdue)},
        )
        return upcoming, overdue, None

    except (httpx.HTTPError, json.JSONDecodeError) as e:
        logger.error("Todoist API request failed", extra={"error": str(e)})  # noqa: TRY400 - network or JSON error; shown on the dashboard
        return [], [], f"Failed to connect to Todoist: {e}"
    except Exception as e:
        logger.exception("Error fetching Todoist data", extra={"error": str(e)})
        return [], [], f"Error fetching Todoist data: {e}"
