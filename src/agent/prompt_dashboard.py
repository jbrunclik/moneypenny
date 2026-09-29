"""Planner dashboard context rendered into the dynamic prompt.

Split out of prompts.py (Sep 2026); prompts.py assembles the final prompts.
"""

import json
from typing import Any


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
        health_data: dict[str, Any] = {}
        if health.get("training_readiness"):
            health_data["training_readiness"] = health["training_readiness"]
        if health.get("sleep"):
            health_data["sleep"] = health["sleep"]
        if health.get("resting_hr") is not None:
            health_data["resting_hr"] = health["resting_hr"]
        if health.get("stress_avg") is not None:
            health_data["stress_avg"] = health["stress_avg"]
        if health.get("hrv_status"):
            health_data["hrv_status"] = health["hrv_status"]
        if health.get("body_battery") is not None:
            health_data["body_battery"] = health["body_battery"]
        if health.get("steps_today") is not None:
            health_data["steps_today"] = health["steps_today"]
        if health.get("recent_activities"):
            health_data["recent_activities"] = health["recent_activities"]
        if health_data:
            schedule_data["health_summary"] = health_data

    # Process days
    for day in dashboard.get("days", []):
        events = day.get("events", [])
        tasks = day.get("tasks", [])
        weather = day.get("weather")

        # Skip days with no content at all
        if not events and not tasks and not weather:
            continue

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
