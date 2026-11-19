"""Todoist completed-task history (list_completed).

Todoist answers by completion date for at most 3 months per request; the
range is taken as APP_TIMEZONE dates with `until` inclusive.
"""

from __future__ import annotations

from datetime import UTC, date, timedelta

from src.agent.tools import todoist_client
from src.agent.tools.todoist_client import TodoistParams
from src.agent.tools.todoist_tasks import fetch_name_map
from src.config import Config
from src.db.models.timestamps import from_db
from src.utils.clock import local_date_start, local_today, to_local, utc_now

COMPLETED_ENDPOINT = "/tasks/completed/by_completion_date"
COMPLETED_DEFAULT_DAYS = 7
COMPLETED_MAX_DAYS = 92  # Todoist's limit is 3 months per request


def _api_instant(day: date) -> str:
    """Local midnight at the start of `day`, as the API's UTC timestamp."""
    return local_date_start(day).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _range(since: str | None, until: str | None) -> tuple[date, date] | str:
    """The inclusive local date range, or an error message."""
    try:
        end = date.fromisoformat(until) if until else local_today(utc_now())
        start = (
            date.fromisoformat(since) if since else end - timedelta(days=COMPLETED_DEFAULT_DAYS - 1)
        )
    except ValueError:
        return "since and until must be dates as YYYY-MM-DD"
    if start > end:
        return f"since ({start}) is after until ({end})"
    if (end - start).days + 1 > COMPLETED_MAX_DAYS:
        return "Todoist returns at most 3 months of completed tasks per call - narrow the range"
    return start, end


def _completed_local(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return to_local(from_db(value)).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def todoist_list_completed(
    token: str,
    since: str | None = None,
    until: str | None = None,
    project_id: str | None = None,
) -> TodoistParams:
    """Tasks completed between two local dates (default: the last 7 days)."""
    bounds = _range(since, until)
    if isinstance(bounds, str):
        return {"error": bounds, "retriable": False}
    start, end = bounds
    params: TodoistParams = {
        "since": _api_instant(start),
        "until": _api_instant(end + timedelta(days=1)),
        "limit": 200,
    }
    if project_id:
        params["project_id"] = project_id
    items = todoist_client.todoist_api_request("GET", COMPLETED_ENDPOINT, token, params=params)
    tasks = items if isinstance(items, list) else []
    truncated = max(0, len(tasks) - Config.TODOIST_MAX_TASK_RESULTS)
    tasks = sorted(tasks, key=lambda t: str(t.get("completed_at") or ""), reverse=True)
    tasks = tasks[: Config.TODOIST_MAX_TASK_RESULTS]
    projects: dict[str, str] = {}
    if any(t.get("project_id") for t in tasks):
        projects = fetch_name_map(
            token, "/projects", "Failed to fetch projects for completed tasks"
        )
    result: TodoistParams = {
        "action": "list_completed",
        "since": start.isoformat(),
        "until": end.isoformat(),
        "count": len(tasks),
        "tasks": [
            {
                "id": t.get("id"),
                "content": t.get("content"),
                "project_name": projects.get(str(t.get("project_id")), None),
                "completed_at": _completed_local(t.get("completed_at")),
            }
            for t in tasks
        ],
    }
    if truncated:
        result["truncated"] = f"{truncated} more completed tasks; narrow the range to see them"
    return result
