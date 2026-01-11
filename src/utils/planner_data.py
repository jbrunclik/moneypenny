"""Planner data utilities for fetching and formatting dashboard data.

This module provides functions to fetch Todoist tasks, Google Calendar events,
and weather forecasts for the planner dashboard.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

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
    organizer: dict[str, Any] | None = None  # Event organizer/creator
    calendar_id: str | None = None  # Source calendar ID
    calendar_summary: str | None = None  # Source calendar name


@dataclass
class PlannerWeather:
    """Weather forecast for a specific day."""

    temperature_high: float | None = None  # Celsius
    temperature_low: float | None = None  # Celsius
    precipitation: float = 0.0  # Total mm for the day
    symbol_code: str | None = None  # Weather symbol (e.g., "clearsky_day", "rain")
    summary: str = ""  # Human-readable summary


@dataclass
class PlannerDay:
    """A single day in the planner dashboard."""

    date: str  # YYYY-MM-DD
    day_name: str  # "Today", "Tomorrow", "Wednesday", etc.
    events: list[PlannerEvent] = field(default_factory=list)
    tasks: list[PlannerTask] = field(default_factory=list)
    weather: PlannerWeather | None = None  # Weather forecast for this day


@dataclass
class PlannerDashboard:
    """The complete planner dashboard data."""

    days: list[PlannerDay]  # 7 days starting from today
    overdue_tasks: list[PlannerTask] = field(default_factory=list)
    todoist_connected: bool = False
    calendar_connected: bool = False
    weather_connected: bool = False
    todoist_error: str | None = None
    calendar_error: str | None = None
    weather_error: str | None = None
    server_time: str = ""  # ISO timestamp
    weather_location: str | None = None  # Location name for weather


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

    # Extract organizer information
    organizer_data = event.get("organizer")
    organizer = None
    if organizer_data:
        organizer = {
            "email": organizer_data.get("email"),
            "display_name": organizer_data.get("displayName"),
            "self": organizer_data.get("self", False),
        }

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
        organizer=organizer,
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
    calendar_ids: list[str] | None = None,
) -> tuple[list[PlannerEvent], str | None]:
    """Fetch Google Calendar events from multiple calendars in parallel.

    Args:
        access_token: The user's Google Calendar access token
        calendar_ids: List of calendar IDs to fetch (defaults to ["primary"])

    Returns:
        Tuple of (events, error_message)
        - events: Combined events from all calendars
        - error_message: Error message if any failures occurred
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import requests

    logger.debug("Fetching calendar dashboard data")

    if not calendar_ids:
        calendar_ids = ["primary"]

    headers = {"Authorization": f"Bearer {access_token}"}

    # First, fetch calendar metadata to get proper calendar names
    calendar_names: dict[str, str] = {}
    try:
        response = requests.get(
            f"{Config.GOOGLE_CALENDAR_API_BASE_URL}/users/me/calendarList",
            headers=headers,
            timeout=Config.GOOGLE_CALENDAR_API_TIMEOUT,
        )
        if response.status_code == 200:
            calendar_list = response.json().get("items", [])
            for cal in calendar_list:
                cal_id = cal.get("id")
                cal_summary = cal.get("summary")
                if cal_id and cal_summary:
                    calendar_names[cal_id] = cal_summary
                # Also map "primary" to the actual primary calendar's name
                if cal.get("primary", False):
                    calendar_names["primary"] = cal_summary
        else:
            logger.warning(
                "Failed to fetch calendar list",
                extra={"status": response.status_code},
            )
    except Exception as e:
        logger.warning("Failed to fetch calendar names", extra={"error": str(e)})

    # Calculate time range (next 7 days)
    now = datetime.utcnow()
    time_min = now.isoformat() + "Z"
    time_max = (now + timedelta(days=7)).isoformat() + "Z"

    params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": True,
        "orderBy": "startTime",
        "maxResults": 100,
    }

    all_events: list[PlannerEvent] = []
    errors: list[tuple[str, str]] = []  # (calendar_id, error_message)
    seen_event_ids: set[str] = set()  # Track event IDs to prevent duplicates

    def fetch_single_calendar(
        calendar_id: str,
    ) -> tuple[str, list[dict[str, Any]] | None, str | None, str | None, bool]:
        """Fetch events from a single calendar.

        Returns: (calendar_id, events, calendar_name, error_message, is_primary)
        """
        try:
            # URL-encode the calendar ID to handle special characters like # in holiday calendars
            encoded_calendar_id = quote(calendar_id, safe="")
            response = requests.get(
                f"{Config.GOOGLE_CALENDAR_API_BASE_URL}/calendars/{encoded_calendar_id}/events",
                headers=headers,
                params=params,  # type: ignore[arg-type]
                timeout=Config.GOOGLE_CALENDAR_API_TIMEOUT,
            )

            # Handle specific error codes
            if response.status_code == 401:
                return calendar_id, None, None, "Access expired", False
            elif response.status_code == 403:
                return calendar_id, None, None, "Permission denied", False
            elif response.status_code == 404:
                return calendar_id, None, None, "Calendar not found", False
            elif response.status_code >= 400:
                logger.warning(
                    "Calendar API error",
                    extra={"calendar_id": calendar_id, "status": response.status_code},
                )
                return calendar_id, None, None, f"API error ({response.status_code})", False

            data = response.json()
            events = data.get("items", [])

            # Check if this is the primary calendar
            is_primary = calendar_id == "primary"

            # Get calendar name from pre-fetched calendar_names map
            calendar_name = calendar_names.get(calendar_id, calendar_id)

            return calendar_id, events, calendar_name, None, is_primary

        except requests.Timeout:
            logger.warning("Calendar fetch timeout", extra={"calendar_id": calendar_id})
            return calendar_id, None, None, "Request timeout", False
        except requests.RequestException as e:
            logger.error(
                "Calendar fetch failed", extra={"calendar_id": calendar_id, "error": str(e)}
            )
            return calendar_id, None, None, "Connection error", False
        except Exception as e:
            logger.error(
                "Unexpected calendar fetch error",
                extra={"calendar_id": calendar_id, "error": str(e)},
                exc_info=True,
            )
            return calendar_id, None, None, "Unexpected error", False

    # Fetch all calendars in parallel (max 5 concurrent)
    with ThreadPoolExecutor(max_workers=min(len(calendar_ids), 5)) as executor:
        futures = {executor.submit(fetch_single_calendar, cid): cid for cid in calendar_ids}

        for future in as_completed(futures):
            calendar_id, events, calendar_name, error, is_primary = future.result()

            if error:
                errors.append((calendar_id, error))
                logger.debug(
                    "Calendar fetch failed", extra={"calendar_id": calendar_id, "error": error}
                )
                continue

            if calendar_name:
                calendar_names[calendar_id] = calendar_name

            if events:
                # Format events with calendar metadata
                for event in events:
                    event_id = event.get("id")
                    if not event_id:
                        continue

                    # Skip duplicate events (can happen when both "primary" and actual primary calendar ID are selected)
                    if event_id in seen_event_ids:
                        logger.debug(
                            "Skipping duplicate event",
                            extra={"event_id": event_id, "calendar_id": calendar_id},
                        )
                        continue

                    seen_event_ids.add(event_id)

                    planner_event = _format_event_for_dashboard(event)
                    # Normalize calendar_id - always use "primary" for the primary calendar
                    planner_event.calendar_id = "primary" if is_primary else calendar_id
                    planner_event.calendar_summary = calendar_name or calendar_id
                    all_events.append(planner_event)

    # Sort combined events by start time
    all_events.sort(key=lambda e: e.start or e.start_date or "")

    # Log results
    logger.debug(
        "Calendar dashboard data fetched",
        extra={
            "event_count": len(all_events),
            "calendars_requested": len(calendar_ids),
            "calendars_succeeded": len(calendar_ids) - len(errors),
            "calendars_failed": len(errors),
        },
    )

    # Determine overall error message
    error_msg = None
    if len(errors) == len(calendar_ids):
        # All calendars failed
        if any("expired" in err.lower() for _, err in errors):
            error_msg = "Google Calendar access has expired. Please reconnect in Settings."
        else:
            error_msg = "Failed to fetch any calendars. Please check your connection."
    elif errors:
        # Partial failure - show which calendars failed
        failed_names = [calendar_names.get(cid, cid) for cid, _ in errors[:3]]
        if len(errors) > 3:
            error_msg = f"Some calendars failed to load: {', '.join(failed_names)}, and {len(errors) - 3} more"
        else:
            error_msg = f"Some calendars failed to load: {', '.join(failed_names)}"

    return all_events, error_msg


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
        # Convert weather
        weather = None
        if day_data.get("weather"):
            weather = PlannerWeather(**day_data["weather"])
        # Create day
        days.append(
            PlannerDay(
                date=day_data["date"],
                day_name=day_data["day_name"],
                events=events,
                tasks=tasks,
                weather=weather,
            )
        )

    # Convert overdue tasks
    overdue_tasks = [PlannerTask(**task_data) for task_data in data.get("overdue_tasks", [])]

    return PlannerDashboard(
        days=days,
        overdue_tasks=overdue_tasks,
        todoist_connected=data.get("todoist_connected", False),
        calendar_connected=data.get("calendar_connected", False),
        weather_connected=data.get("weather_connected", False),
        todoist_error=data.get("todoist_error"),
        calendar_error=data.get("calendar_error"),
        weather_error=data.get("weather_error"),
        server_time=data.get("server_time", ""),
        weather_location=data.get("weather_location"),
    )


def build_planner_dashboard(
    todoist_token: str | None = None,
    calendar_token: str | None = None,
    user_id: str | None = None,
    force_refresh: bool = False,
    db: Any = None,
) -> PlannerDashboard:
    """Build the complete planner dashboard data with SQLite caching.

    Fetches data from Todoist, Google Calendar, and weather (if configured)
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
            "weather_configured": bool(Config.WEATHER_LOCATION),
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
        weather_connected=bool(Config.WEATHER_LOCATION),
        server_time=server_time,
    )

    # Fetch all dashboard resources in parallel (Todoist, Calendar, Weather)
    from concurrent.futures import ThreadPoolExecutor

    def fetch_todoist_if_available() -> tuple[list[Any], list[Any], str | None]:
        """Fetch Todoist data if token available."""
        if todoist_token:
            return fetch_todoist_dashboard_data(todoist_token)
        return [], [], None

    def fetch_calendar_if_available() -> tuple[list[PlannerEvent], str | None]:
        """Fetch Google Calendar data if token available."""
        if calendar_token:
            # Get user's selected calendar IDs
            selected_calendar_ids = ["primary"]  # Default
            if user_id and db:
                try:
                    current_user = db.get_user_by_id(user_id)
                    if current_user and current_user.google_calendar_selected_ids:
                        selected_calendar_ids = current_user.google_calendar_selected_ids
                except Exception as e:
                    logger.warning(
                        "Failed to get user calendar selection, using primary",
                        extra={"user_id": user_id, "error": str(e)},
                    )

            return fetch_calendar_dashboard_data(calendar_token, selected_calendar_ids)
        return [], None

    def fetch_weather_if_available() -> tuple[Any | None, str | None]:
        """Fetch weather data if location configured."""
        if Config.WEATHER_LOCATION:
            try:
                from src.utils.weather import get_weather_for_location

                forecast = get_weather_for_location(
                    Config.WEATHER_LOCATION,
                    db=db,
                    force_refresh=force_refresh,
                )
                return forecast, None
            except Exception as e:
                logger.error(
                    "Failed to fetch weather for planner",
                    extra={"error": str(e), "location": Config.WEATHER_LOCATION},
                    exc_info=True,
                )
                return None, f"Weather error: {e}"
        return None, None

    # Fetch all resources in parallel
    with ThreadPoolExecutor(max_workers=3) as executor:
        todoist_future = executor.submit(fetch_todoist_if_available)
        calendar_future = executor.submit(fetch_calendar_if_available)
        weather_future = executor.submit(fetch_weather_if_available)

        # Wait for all results
        tasks_7_days, overdue_tasks, todoist_error = todoist_future.result()
        events, calendar_error = calendar_future.result()
        forecast, weather_error = weather_future.result()

    # Process Todoist data
    dashboard.overdue_tasks = overdue_tasks
    dashboard.todoist_error = todoist_error

    for task in tasks_7_days:
        if task.due_date and task.due_date in date_to_day:
            date_to_day[task.due_date].tasks.append(task)
        elif not task.due_date:
            # Tasks without due dates go to "Today"
            days[0].tasks.append(task)

    # Process Google Calendar data
    dashboard.calendar_error = calendar_error

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

    # Process Weather data
    if forecast:
        dashboard.weather_location = forecast.location

        # Group weather periods by date and calculate daily stats
        weather_by_date: dict[str, list[Any]] = {}
        for period in forecast.periods:
            # Parse period time to get date
            period_time = _parse_datetime(period.time)
            if period_time:
                date_key = period_time.strftime("%Y-%m-%d")
                if date_key not in weather_by_date:
                    weather_by_date[date_key] = []
                weather_by_date[date_key].append(period)

        # Calculate daily weather summaries
        for date_key, periods in weather_by_date.items():
            if date_key in date_to_day:
                temps = [p.temperature for p in periods]
                precips = [p.precipitation for p in periods]
                # Find the most common symbol for the day (noon period preferred)
                symbols = [p.symbol_code for p in periods if p.symbol_code]
                symbol = symbols[len(symbols) // 2] if symbols else None

                temp_high = max(temps) if temps else None
                temp_low = min(temps) if temps else None
                total_precip = sum(precips)

                # Build summary
                summary_parts = []
                if temp_high and temp_low:
                    summary_parts.append(f"{temp_low:.1f}-{temp_high:.1f}°C")
                if total_precip > 0:
                    summary_parts.append(f"{total_precip:.1f}mm rain")

                date_to_day[date_key].weather = PlannerWeather(
                    temperature_high=temp_high,
                    temperature_low=temp_low,
                    precipitation=total_precip,
                    symbol_code=symbol,
                    summary=", ".join(summary_parts) if summary_parts else "No data",
                )
    elif weather_error:
        dashboard.weather_error = weather_error
    elif Config.WEATHER_LOCATION:
        dashboard.weather_error = "Unable to fetch weather data"

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
