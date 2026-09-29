"""Planner dashboard and planner conversation schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.api.schemas.chat import MessageResponse


class PlannerTaskResponse(BaseModel):
    """A task from Todoist for the planner dashboard."""

    id: str
    content: str
    description: str = ""
    due_date: str | None = Field(default=None, description="Due date in YYYY-MM-DD format")
    due_string: str | None = Field(
        default=None, description="Human-readable due string (e.g., 'tomorrow at 3pm')"
    )
    priority: int = Field(default=1, ge=1, le=4, description="Priority 1-4 (4 is highest)")
    project_name: str | None = None
    section_name: str | None = None
    labels: list[str] = Field(default_factory=list)
    is_recurring: bool = False
    url: str | None = Field(default=None, description="Direct URL to task in Todoist")


class PlannerEventAttendeeResponse(BaseModel):
    """An attendee on a calendar event."""

    email: str | None = None
    response_status: str | None = Field(
        default=None, description="RSVP status: accepted/tentative/declined/needsAction"
    )
    self: bool = Field(default=False, description="True if this is the current user")


class PlannerEventOrganizerResponse(BaseModel):
    """The organizer/creator of a calendar event."""

    email: str | None = None
    display_name: str | None = Field(default=None, description="Display name of organizer")
    self: bool = Field(default=False, description="True if this is the current user")


class PlannerEventResponse(BaseModel):
    """A calendar event for the planner dashboard."""

    id: str
    summary: str
    description: str | None = None
    start: str | None = Field(default=None, description="Start datetime (ISO format)")
    end: str | None = Field(default=None, description="End datetime (ISO format)")
    start_date: str | None = Field(
        default=None, description="Start date for all-day events (YYYY-MM-DD)"
    )
    end_date: str | None = Field(
        default=None, description="End date for all-day events (YYYY-MM-DD)"
    )
    location: str | None = None
    html_link: str | None = Field(
        default=None, description="Direct URL to event in Google Calendar"
    )
    is_all_day: bool = False
    attendees: list[PlannerEventAttendeeResponse] = Field(default_factory=list)
    organizer: PlannerEventOrganizerResponse | None = Field(
        default=None, description="Event organizer/creator"
    )
    calendar_id: str | None = Field(
        default=None, description="Source calendar ID (e.g., 'primary', email address)"
    )
    calendar_summary: str | None = Field(default=None, description="Source calendar name/title")


class PlannerWeatherResponse(BaseModel):
    """Weather forecast for a single day."""

    temperature_high: float | None = None
    temperature_low: float | None = None
    precipitation: float = 0.0
    symbol_code: str | None = None
    summary: str = ""


class PlannerHealthSummaryResponse(BaseModel):
    """Health data summary from Garmin."""

    training_readiness: dict[str, Any] | None = None
    sleep: dict[str, Any] | None = None
    stress_avg: float | None = None
    resting_hr: int | None = None
    body_battery: int | None = None
    steps_today: int | None = None
    recent_activities: list[dict[str, Any]] = Field(default_factory=list)


class PlannerDayResponse(BaseModel):
    """A single day in the planner dashboard."""

    date: str = Field(..., description="Date in YYYY-MM-DD format")
    day_name: str = Field(..., description="Day label (Today, Tomorrow, or weekday name)")
    events: list[PlannerEventResponse] = Field(default_factory=list)
    tasks: list[PlannerTaskResponse] = Field(default_factory=list)
    weather: PlannerWeatherResponse | None = Field(
        default=None, description="Weather forecast for this day"
    )


class PlannerDashboardResponse(BaseModel):
    """Complete planner dashboard data."""

    days: list[PlannerDayResponse] = Field(
        ..., description="7 days of events and tasks starting from today"
    )
    overdue_tasks: list[PlannerTaskResponse] = Field(
        default_factory=list, description="Tasks that are past their due date"
    )
    todoist_connected: bool = Field(default=False, description="Whether Todoist is connected")
    calendar_connected: bool = Field(
        default=False, description="Whether Google Calendar is connected"
    )
    garmin_connected: bool = Field(default=False, description="Whether Garmin is connected")
    weather_connected: bool = Field(default=False, description="Whether weather is configured")
    todoist_error: str | None = Field(
        default=None, description="Error message if Todoist fetch failed"
    )
    calendar_error: str | None = Field(
        default=None, description="Error message if Calendar fetch failed"
    )
    garmin_error: str | None = Field(
        default=None, description="Error message if Garmin fetch failed"
    )
    weather_error: str | None = Field(
        default=None, description="Error message if weather fetch failed"
    )
    weather_location: str | None = Field(default=None, description="Location name for weather data")
    health_summary: PlannerHealthSummaryResponse | None = Field(
        default=None, description="Health data from Garmin"
    )
    server_time: str = Field(..., description="Server timestamp for cache validation")


class PlannerConversationResponse(BaseModel):
    """Planner conversation with messages."""

    id: str
    title: str
    model: str
    created_at: str
    updated_at: str
    messages: list[MessageResponse]
    was_reset: bool = Field(
        default=False, description="True if the conversation was auto-reset due to 4am cutoff"
    )


class PlannerResetResponse(BaseModel):
    """Response from planner reset endpoint."""

    success: bool = True
    message: str = "Planner conversation reset"


class PlannerConversationSyncData(BaseModel):
    """Planner conversation data for sync."""

    id: str
    updated_at: str
    message_count: int
    last_reset: str | None = Field(default=None, description="Timestamp of last reset")


class PlannerSyncResponse(BaseModel):
    """Response from planner sync endpoint for real-time synchronization."""

    conversation: PlannerConversationSyncData | None = Field(
        default=None, description="Planner conversation state, or null if no planner exists"
    )
    server_time: str = Field(..., description="Server timestamp in ISO format")
