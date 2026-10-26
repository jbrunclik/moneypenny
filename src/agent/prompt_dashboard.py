"""Planner dashboard context rendered into the dynamic prompt.

Split out of prompts.py (Sep 2026); prompts.py assembles the final prompts.
"""

import json
from typing import Any

# Health summary fields in output order; the numeric ones count when zero
_HEALTH_FIELDS = (
    "training_readiness",
    "sleep",
    "resting_hr",
    "stress_avg",
    "hrv_status",
    "body_battery",
    "steps_today",
    "recent_activities",
)
_NUMERIC_HEALTH_FIELDS = frozenset({"resting_hr", "stress_avg", "body_battery", "steps_today"})


def _health_data(health: dict[str, Any]) -> dict[str, Any]:
    """The Garmin health fields that carry a value."""
    health_data: dict[str, Any] = {}
    for key in _HEALTH_FIELDS:
        value = health.get(key)
        present = value is not None if key in _NUMERIC_HEALTH_FIELDS else bool(value)
        if present:
            health_data[key] = value
    return health_data


def _day_data(day: dict[str, Any]) -> dict[str, Any] | None:
    """One day's events, tasks and weather, or None for a day with none of them."""
    events = day.get("events", [])
    tasks = day.get("tasks", [])
    weather = day.get("weather")

    # Skip days with no content at all
    if not events and not tasks and not weather:
        return None

    day_data: dict[str, Any] = {
        "day_name": day.get("day_name", "Unknown"),
        "date": day.get("date", ""),
        "events": [
            {
                "summary": event.get("summary", "(No title)"),
                "start": event.get("start"),
                "end": event.get("end"),
                "start_date": event.get("start_date"),
                "end_date": event.get("end_date"),
                "is_all_day": event.get("is_all_day", False),
                "location": event.get("location"),
                "attendees": event.get("attendees", []),
                "organizer": event.get("organizer"),
                "calendar_id": event.get("calendar_id"),
                "calendar_summary": event.get("calendar_summary"),
            }
            for event in events
        ],
        "tasks": [
            {
                "content": task.get("content", ""),
                "priority": task.get("priority", 1),
                "project_name": task.get("project_name"),
                "section_name": task.get("section_name"),
                "due_date": task.get("due_date"),
                "is_recurring": task.get("is_recurring", False),
                "labels": task.get("labels", []),
            }
            for task in tasks
        ],
    }

    if weather and isinstance(weather, dict):
        day_data["weather"] = {
            "high_c": weather.get("temperature_high"),
            "low_c": weather.get("temperature_low"),
            "precipitation_mm": weather.get("precipitation", 0),
            "summary": weather.get("summary", ""),
        }
    return day_data


def get_dashboard_context_prompt(dashboard: dict[str, Any]) -> str:
    """Format dashboard data for injection into the planner system prompt.

    Uses JSON format for better structure and semantic clarity for the LLM.

    Args:
        dashboard: The planner dashboard data dict

    Returns:
        JSON-formatted string with the dashboard context
    """

    # Build structured JSON data
    schedule_data: dict[str, Any] = {
        "integrations": {
            "todoist_connected": dashboard.get("todoist_connected", False),
            "calendar_connected": dashboard.get("calendar_connected", False),
            "garmin_connected": dashboard.get("garmin_connected", False),
            "todoist_error": dashboard.get("todoist_error"),
            "calendar_error": dashboard.get("calendar_error"),
            "garmin_error": dashboard.get("garmin_error"),
            "weather_connected": dashboard.get("weather_connected", False),
            "weather_error": dashboard.get("weather_error"),
        },
        "overdue_tasks": [
            {
                "content": task.get("content", ""),
                "priority": task.get("priority", 1),
                "project_name": task.get("project_name"),
                "due_string": task.get("due_string"),
                "due_date": task.get("due_date"),
                "is_recurring": task.get("is_recurring", False),
                "labels": task.get("labels", []),
            }
            for task in dashboard.get("overdue_tasks", [])
        ],
        "days": [],
    }

    # Add health summary if Garmin is connected
    health = dashboard.get("health_summary")
    if health and isinstance(health, dict):
        health_data = _health_data(health)
        if health_data:
            schedule_data["health_summary"] = health_data

    # Process days
    for day in dashboard.get("days", []):
        day_data = _day_data(day)
        if day_data is not None:
            schedule_data["days"].append(day_data)

    # Format as JSON with explanation (ensure_ascii=False: Czech event titles
    # must reach the model as real characters, not \uXXXX escapes)
    json_str = json.dumps(schedule_data, indent=2, ensure_ascii=False)
    return f"""

# Current Schedule Overview

The following JSON contains your complete schedule data:

```json
{json_str}
```

**Priority levels**: 1 (lowest) to 4 (highest/urgent)
**Integration status**: Check `integrations` object for connection status and errors
**Overdue tasks**: Listed separately in `overdue_tasks` array (requires immediate attention)
**Days**: Array of upcoming days with events (calendar), tasks (Todoist), and weather forecast
**Weather**: Temperature range and precipitation for each day (if location configured)
**Health data**: Current vitals, sleep, training readiness, and recent activities from Garmin (if connected)
"""
