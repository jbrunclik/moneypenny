"""Planner dashboard data shapes and their conversion from the cached dict."""

from dataclasses import dataclass, field
from typing import Any


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
class PlannerHealthSummary:
    """Health data from Garmin for the planner dashboard."""

    training_readiness: dict[str, Any] | None = None
    training_status: dict[str, Any] | None = None
    sleep: dict[str, Any] | None = None
    stress_avg: float | None = None
    resting_hr: int | None = None
    hrv_status: str | None = None
    body_battery: int | None = None
    steps_today: int | None = None
    recent_activities: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PlannerDashboard:
    """The complete planner dashboard data."""

    days: list[PlannerDay]  # 7 days starting from today
    overdue_tasks: list[PlannerTask] = field(default_factory=list)
    todoist_connected: bool = False
    calendar_connected: bool = False
    garmin_connected: bool = False
    weather_connected: bool = False
    todoist_error: str | None = None
    calendar_error: str | None = None
    garmin_error: str | None = None
    weather_error: str | None = None
    server_time: str = ""  # ISO timestamp
    weather_location: str | None = None  # Location name for weather
    health_summary: PlannerHealthSummary | None = None


def _day_from_dict(day_data: dict[str, Any]) -> PlannerDay:
    """Convert one cached day back to a PlannerDay."""
    weather = None
    if day_data.get("weather"):
        weather = PlannerWeather(**day_data["weather"])
    return PlannerDay(
        date=day_data["date"],
        day_name=day_data["day_name"],
        events=[PlannerEvent(**event_data) for event_data in day_data.get("events", [])],
        tasks=[PlannerTask(**task_data) for task_data in day_data.get("tasks", [])],
        weather=weather,
    )


def dashboard_from_dict(data: dict[str, Any]) -> PlannerDashboard:
    """Convert the cached dict (``asdict`` of a dashboard) back to a PlannerDashboard."""
    health_summary = None
    if data.get("health_summary"):
        health_summary = PlannerHealthSummary(**data["health_summary"])

    return PlannerDashboard(
        days=[_day_from_dict(day_data) for day_data in data.get("days", [])],
        overdue_tasks=[PlannerTask(**task_data) for task_data in data.get("overdue_tasks", [])],
        todoist_connected=data.get("todoist_connected", False),
        calendar_connected=data.get("calendar_connected", False),
        garmin_connected=data.get("garmin_connected", False),
        weather_connected=data.get("weather_connected", False),
        todoist_error=data.get("todoist_error"),
        calendar_error=data.get("calendar_error"),
        garmin_error=data.get("garmin_error"),
        weather_error=data.get("weather_error"),
        server_time=data.get("server_time", ""),
        weather_location=data.get("weather_location"),
        health_summary=health_summary,
    )
