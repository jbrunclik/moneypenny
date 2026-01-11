"""Planner data utilities for fetching and formatting dashboard data.

This module provides functions to fetch Todoist tasks and Google Calendar events
for the planner dashboard. It reuses the API request logic from the tools package.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PlannerTask:
    """A task from Todoist for the planner dashboard."""

    id: str
    content: str
    description: str = ""
    due_date: str | None = None
    due_string: str | None = None
    priority: int = 1  # 1-4, where 4 is highest
    project_name: str | None = None
    section_name: str | None = None
    labels: list[str] = field(default_factory=list)
    is_recurring: bool = False
    url: str | None = None


@dataclass
class PlannerEvent:
    """A calendar event for the planner dashboard."""

    id: str
    summary: str
    description: str | None = None
    start: str | None = None  # ISO datetime or None for all-day
    end: str | None = None
    start_date: str | None = None  # YYYY-MM-DD for all-day events
    end_date: str | None = None
    location: str | None = None
    html_link: str | None = None
    is_all_day: bool = False
    attendees: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PlannerDay:
    """A single day in the planner dashboard."""

    date: str  # YYYY-MM-DD
    day_name: str  # "Today", "Tomorrow", "Wednesday", etc.
    events: list[PlannerEvent] = field(default_factory=list)
    tasks: list[PlannerTask] = field(default_factory=list)


@dataclass
class PlannerDashboard:
    """The complete planner dashboard data."""

    days: list[PlannerDay]  # 7 days starting from today
    overdue_tasks: list[PlannerTask] = field(default_factory=list)
    todoist_connected: bool = False
    calendar_connected: bool = False
    todoist_error: str | None = None
    calendar_error: str | None = None
    server_time: str = ""  # ISO timestamp


def _get_day_name(date: datetime, today: datetime) -> str:
    """Get a human-readable name for a day relative to today."""
    days_diff = (date.date() - today.date()).days
    if days_diff == 0:
        return "Today"
    elif days_diff == 1:
        return "Tomorrow"
    else:
        return date.strftime("%A")  # Full weekday name


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse a date string (YYYY-MM-DD) to datetime."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None


def _parse_datetime(datetime_str: str | None) -> datetime | None:
    """Parse an ISO datetime string to datetime."""
    if not datetime_str:
        return None
    try:
        # Handle timezone-aware strings
        if datetime_str.endswith("Z"):
            datetime_str = datetime_str[:-1] + "+00:00"
        return datetime.fromisoformat(datetime_str)
    except ValueError:
        return None


def _format_task_for_dashboard(
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


def _format_event_for_dashboard(event: dict[str, Any]) -> PlannerEvent:
    """Convert a raw Google Calendar event to a PlannerEvent."""
    start = event.get("start", {})
    end = event.get("end", {})

    is_all_day = "date" in start and "dateTime" not in start

    return PlannerEvent(
        id=event.get("id", ""),
        summary=event.get("summary", "(No title)"),
        description=event.get("description"),
        start=start.get("dateTime"),
        end=end.get("dateTime"),
        start_date=start.get("date"),
        end_date=end.get("date"),
        location=event.get("location"),
        html_link=event.get("htmlLink"),
        is_all_day=is_all_day,
        attendees=[
            {
                "email": a.get("email"),
                "response_status": a.get("responseStatus"),
                "self": a.get("self", False),
            }
            for a in event.get("attendees", [])
        ],
    )


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
    import requests

    logger.debug("Fetching Todoist dashboard data")

    tasks_7_days: list[PlannerTask] = []
    overdue_tasks: list[PlannerTask] = []

    try:
        headers = {"Authorization": f"Bearer {access_token}"}

        # Fetch tasks with filter: "7 days | overdue"
        # This gets both next 7 days and overdue in one request
        response = requests.get(
            f"{Config.TODOIST_API_BASE_URL}/tasks",
            headers=headers,
            params={"filter": "7 days | overdue"},
            timeout=Config.TODOIST_API_TIMEOUT,
        )

        if response.status_code == 401 or response.status_code == 403:
            return [], [], "Todoist access has expired. Please reconnect in Settings."

        if response.status_code >= 400:
            logger.warning(
                "Todoist API error",
                extra={"status_code": response.status_code, "error": response.text},
            )
            return [], [], f"Todoist API error ({response.status_code})"

        tasks = response.json()
        if not isinstance(tasks, list):
            tasks = []

        # Build section and project maps for enrichment
        section_ids = {t.get("section_id") for t in tasks if t.get("section_id")}
        project_ids = {t.get("project_id") for t in tasks if t.get("project_id")}

        section_map: dict[str, str] = {}
        project_map: dict[str, str] = {}

        # Fetch sections for enrichment
        if section_ids:
            try:
                sections_response = requests.get(
                    f"{Config.TODOIST_API_BASE_URL}/sections",
                    headers=headers,
                    timeout=Config.TODOIST_API_TIMEOUT,
                )
                if sections_response.status_code == 200:
                    sections = sections_response.json()
                    if isinstance(sections, list):
                        section_map = {s["id"]: s["name"] for s in sections if s.get("id")}
            except Exception as e:
                logger.warning(
                    "Failed to fetch sections for dashboard",
                    extra={"error": str(e)},
                )

        # Fetch projects for enrichment
        if project_ids:
            try:
                projects_response = requests.get(
                    f"{Config.TODOIST_API_BASE_URL}/projects",
                    headers=headers,
                    timeout=Config.TODOIST_API_TIMEOUT,
                )
                if projects_response.status_code == 200:
                    projects = projects_response.json()
                    if isinstance(projects, list):
                        project_map = {p["id"]: p["name"] for p in projects if p.get("id")}
            except Exception as e:
                logger.warning(
                    "Failed to fetch projects for dashboard",
                    extra={"error": str(e)},
                )

        # Convert and categorize tasks
        today = datetime.now().date()

        for task in tasks:
            planner_task = _format_task_for_dashboard(task, section_map, project_map)

            # Determine if task is overdue or upcoming
            if planner_task.due_date:
                task_date = _parse_date(planner_task.due_date)
                if task_date and task_date.date() < today:
                    overdue_tasks.append(planner_task)
                else:
                    tasks_7_days.append(planner_task)
            else:
                # Tasks without due dates from "7 days" filter go to upcoming
                tasks_7_days.append(planner_task)

        logger.debug(
            "Todoist dashboard data fetched",
            extra={
                "tasks_7_days": len(tasks_7_days),
                "overdue": len(overdue_tasks),
            },
        )

        return tasks_7_days, overdue_tasks, None

    except requests.RequestException as e:
        logger.error("Todoist API request failed", extra={"error": str(e)})
        return [], [], f"Failed to connect to Todoist: {e}"
    except Exception as e:
        logger.error("Error fetching Todoist data", extra={"error": str(e)}, exc_info=True)
        return [], [], f"Error fetching Todoist data: {e}"


def fetch_calendar_dashboard_data(
    access_token: str,
) -> tuple[list[PlannerEvent], str | None]:
    """Fetch Google Calendar events for the next 7 days.

    Args:
        access_token: The user's Google Calendar access token

    Returns:
        Tuple of (events, error_message)
        events: Events in the next 7 days
        error_message: Error message if any, None otherwise
    """
    import requests

    logger.debug("Fetching Google Calendar dashboard data")

    try:
        headers = {"Authorization": f"Bearer {access_token}"}

        # Calculate time range
        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(days=7)).isoformat() + "Z"

        response = requests.get(
            f"{Config.GOOGLE_CALENDAR_API_BASE_URL}/calendars/primary/events",
            headers=headers,
            params={  # type: ignore[arg-type]
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": True,
                "orderBy": "startTime",
                "maxResults": 100,
            },
            timeout=Config.GOOGLE_CALENDAR_API_TIMEOUT,
        )

        if response.status_code == 401:
            return [], "Google Calendar access has expired. Please reconnect in Settings."

        if response.status_code >= 400:
            logger.warning(
                "Google Calendar API error",
                extra={"status_code": response.status_code, "error": response.text},
            )
            return [], f"Google Calendar API error ({response.status_code})"

        data = response.json()
        raw_events = data.get("items", [])

        events = [_format_event_for_dashboard(event) for event in raw_events]

        logger.debug(
            "Google Calendar dashboard data fetched",
            extra={"event_count": len(events)},
        )

        return events, None

    except requests.RequestException as e:
        logger.error("Google Calendar API request failed", extra={"error": str(e)})
        return [], f"Failed to connect to Google Calendar: {e}"
    except Exception as e:
        logger.error(
            "Error fetching Google Calendar data",
            extra={"error": str(e)},
            exc_info=True,
        )
        return [], f"Error fetching calendar data: {e}"


def _dict_to_dashboard(data: dict[str, Any]) -> PlannerDashboard:
    """Convert cached dict to PlannerDashboard dataclass.

    Args:
        data: Dictionary representation of dashboard

    Returns:
        PlannerDashboard instance
    """
    # Convert nested dicts to dataclass instances
    days = []
    for day_data in data.get("days", []):
        # Convert events
        events = [PlannerEvent(**event_data) for event_data in day_data.get("events", [])]
        # Convert tasks
        tasks = [PlannerTask(**task_data) for task_data in day_data.get("tasks", [])]
        # Create day
        days.append(
            PlannerDay(
                date=day_data["date"],
                day_name=day_data["day_name"],
                events=events,
                tasks=tasks,
            )
        )

    # Convert overdue tasks
    overdue_tasks = [PlannerTask(**task_data) for task_data in data.get("overdue_tasks", [])]

    return PlannerDashboard(
        days=days,
        overdue_tasks=overdue_tasks,
        todoist_connected=data.get("todoist_connected", False),
        calendar_connected=data.get("calendar_connected", False),
        todoist_error=data.get("todoist_error"),
        calendar_error=data.get("calendar_error"),
        server_time=data.get("server_time", ""),
    )


def build_planner_dashboard(
    todoist_token: str | None = None,
    calendar_token: str | None = None,
    user_id: str | None = None,
    force_refresh: bool = False,
    db: Any = None,
) -> PlannerDashboard:
    """Build the complete planner dashboard data with SQLite caching.

    Fetches data from both Todoist and Google Calendar (if connected)
    and organizes it into a 7-day view. Uses SQLite cache to share data
    across multiple uwsgi workers.

    Args:
        todoist_token: The user's Todoist access token (None if not connected)
        calendar_token: The user's Google Calendar access token (None if not connected)
        user_id: The user ID for cache key (required for caching)
        force_refresh: Bypass cache and fetch fresh data (for refresh button)
        db: Database instance for caching (optional)

    Returns:
        PlannerDashboard with all data organized by day
    """
    from dataclasses import asdict

    # Check cache if not forcing refresh
    if not force_refresh and user_id and db:
        cached_data = db.get_cached_dashboard(user_id)
        if cached_data:
            logger.debug("Returning cached dashboard", extra={"user_id": user_id})
            # Convert dict back to PlannerDashboard
            return _dict_to_dashboard(cached_data)

    logger.debug(
        "Building fresh planner dashboard",
        extra={
            "todoist_connected": bool(todoist_token),
            "calendar_connected": bool(calendar_token),
            "force_refresh": force_refresh,
        },
    )

    now = datetime.now()
    server_time = now.isoformat()

    # Initialize 7 days
    days: list[PlannerDay] = []
    for i in range(7):
        day_date = now + timedelta(days=i)
        days.append(
            PlannerDay(
                date=day_date.strftime("%Y-%m-%d"),
                day_name=_get_day_name(day_date, now),
            )
        )

    # Create a date-to-day mapping for quick lookup
    date_to_day: dict[str, PlannerDay] = {day.date: day for day in days}

    # Initialize result
    dashboard = PlannerDashboard(
        days=days,
        todoist_connected=bool(todoist_token),
        calendar_connected=bool(calendar_token),
        server_time=server_time,
    )

    # Fetch Todoist data
    if todoist_token:
        tasks_7_days, overdue_tasks, todoist_error = fetch_todoist_dashboard_data(todoist_token)
        dashboard.overdue_tasks = overdue_tasks
        dashboard.todoist_error = todoist_error

        # Distribute tasks to days
        for task in tasks_7_days:
            if task.due_date and task.due_date in date_to_day:
                date_to_day[task.due_date].tasks.append(task)
            elif not task.due_date:
                # Tasks without due dates go to "Today"
                days[0].tasks.append(task)

    # Fetch Google Calendar data
    if calendar_token:
        events, calendar_error = fetch_calendar_dashboard_data(calendar_token)
        dashboard.calendar_error = calendar_error

        # Distribute events to days
        for event in events:
            # Determine the event's date
            if event.start_date:
                event_date = event.start_date
            elif event.start:
                parsed = _parse_datetime(event.start)
                if parsed:
                    event_date = parsed.strftime("%Y-%m-%d")
                else:
                    continue
            else:
                continue

            if event_date in date_to_day:
                date_to_day[event_date].events.append(event)

    # Sort tasks by priority (highest first) and events by time
    for day in days:
        day.tasks.sort(key=lambda t: -t.priority)
        day.events.sort(key=lambda e: e.start or e.start_date or "")

    logger.info(
        "Planner dashboard built",
        extra={
            "total_events": sum(len(d.events) for d in days),
            "total_tasks": sum(len(d.tasks) for d in days),
            "overdue_tasks": len(dashboard.overdue_tasks),
        },
    )

    # Cache the result if user_id and db provided
    if user_id and db:
        dashboard_dict = asdict(dashboard)
        db.cache_dashboard(user_id, dashboard_dict, ttl_seconds=Config.DASHBOARD_CACHE_TTL_SECONDS)
        logger.debug("Dashboard cached", extra={"user_id": user_id})

    return dashboard
