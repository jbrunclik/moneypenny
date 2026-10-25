"""The planner dashboard section of the system prompt (src/agent/prompt_dashboard.py).

The dashboard reaches the prompt as dataclasses.asdict(PlannerDashboard), so
fixtures are built from the real dataclasses. Assertions parse the embedded
JSON rather than comparing prompt text verbatim.
"""

import json
import re
from dataclasses import asdict
from typing import Any

from src.agent.prompt_dashboard import get_dashboard_context_prompt
from src.services.planner_data import (
    PlannerDashboard,
    PlannerDay,
    PlannerEvent,
    PlannerHealthSummary,
    PlannerTask,
    PlannerWeather,
)

TODAY = "2026-10-25"
TOMORROW = "2026-10-26"


def _render(dashboard: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The prompt and the JSON object embedded in it."""
    prompt = get_dashboard_context_prompt(dashboard)
    match = re.search(r"```json\n(.*)\n```", prompt, re.DOTALL)
    assert match, prompt
    return prompt, json.loads(match.group(1))


def _dashboard(**kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("days", [PlannerDay(date=TODAY, day_name="Today")])
    return asdict(PlannerDashboard(**kwargs))


def test_an_empty_dashboard_renders_the_section_with_no_days_or_tasks() -> None:
    prompt, data = _render(_dashboard())
    assert "# Current Schedule Overview" in prompt
    assert data["days"] == []
    assert data["overdue_tasks"] == []
    assert "health_summary" not in data


def test_an_empty_dict_does_not_crash_and_defaults_integrations_to_off() -> None:
    _prompt, data = _render({})
    assert data["integrations"]["todoist_connected"] is False
    assert data["integrations"]["calendar_connected"] is False
    assert data["integrations"]["todoist_error"] is None
    assert data["days"] == []


def test_connection_flags_and_errors_appear_under_integrations() -> None:
    _prompt, data = _render(
        _dashboard(
            todoist_connected=True,
            calendar_connected=True,
            calendar_error="Calendar fetch failed: 401",
            weather_error="Unable to fetch weather data",
        )
    )
    integrations = data["integrations"]
    assert integrations["todoist_connected"] is True
    assert integrations["calendar_error"] == "Calendar fetch failed: 401"
    assert integrations["weather_error"] == "Unable to fetch weather data"
    assert integrations["garmin_error"] is None


def test_a_days_events_appear_with_their_details() -> None:
    event = PlannerEvent(
        id="e1",
        summary="Zubař",
        start="2026-10-25T09:00:00+02:00",
        end="2026-10-25T10:00:00+02:00",
        location="Praha",
        calendar_summary="Rodina",
    )
    _prompt, data = _render(
        _dashboard(days=[PlannerDay(date=TODAY, day_name="Today", events=[event])])
    )
    [day] = data["days"]
    assert (day["day_name"], day["date"]) == ("Today", TODAY)
    [rendered] = day["events"]
    assert rendered["summary"] == "Zubař"
    assert rendered["start"] == "2026-10-25T09:00:00+02:00"
    assert rendered["location"] == "Praha"
    assert rendered["calendar_summary"] == "Rodina"
    assert "weather" not in day


def test_czech_text_reaches_the_prompt_unescaped() -> None:
    event = PlannerEvent(id="e1", summary="Přespolní běh")
    prompt, _data = _render(
        _dashboard(days=[PlannerDay(date=TODAY, day_name="Today", events=[event])])
    )
    assert "Přespolní běh" in prompt


def test_a_days_tasks_appear_with_priority_and_project() -> None:
    task = PlannerTask(
        id="t1",
        content="Zaplatit školku",
        due_date=TODAY,
        priority=4,
        project_name="Domácnost",
        section_name="Platby",
        labels=["peníze"],
    )
    _prompt, data = _render(
        _dashboard(days=[PlannerDay(date=TODAY, day_name="Today", tasks=[task])])
    )
    [rendered] = data["days"][0]["tasks"]
    assert rendered["content"] == "Zaplatit školku"
    assert rendered["priority"] == 4
    assert rendered["project_name"] == "Domácnost"
    assert rendered["section_name"] == "Platby"
    assert rendered["labels"] == ["peníze"]
    assert data["days"][0]["events"] == []


def test_overdue_tasks_are_listed_separately() -> None:
    task = PlannerTask(
        id="t1",
        content="Vrátit knihu",
        due_date="2026-10-20",
        due_string="every week",
        is_recurring=True,
    )
    _prompt, data = _render(_dashboard(overdue_tasks=[task]))
    [rendered] = data["overdue_tasks"]
    assert rendered["content"] == "Vrátit knihu"
    assert rendered["due_date"] == "2026-10-20"
    assert rendered["is_recurring"] is True
    assert data["days"] == []


def test_a_day_with_only_weather_is_kept_and_weather_fields_are_renamed() -> None:
    weather = PlannerWeather(
        temperature_high=14.5, temperature_low=6.0, precipitation=2.3, summary="6.0-14.5°C"
    )
    _prompt, data = _render(
        _dashboard(days=[PlannerDay(date=TOMORROW, day_name="Tomorrow", weather=weather)])
    )
    [day] = data["days"]
    assert day["day_name"] == "Tomorrow"
    assert day["weather"] == {
        "high_c": 14.5,
        "low_c": 6.0,
        "precipitation_mm": 2.3,
        "summary": "6.0-14.5°C",
    }


def test_days_without_events_tasks_or_weather_are_skipped() -> None:
    days = [
        PlannerDay(date=TODAY, day_name="Today"),
        PlannerDay(date=TOMORROW, day_name="Tomorrow", tasks=[PlannerTask(id="t", content="X")]),
    ]
    _prompt, data = _render(_dashboard(days=days))
    assert [d["day_name"] for d in data["days"]] == ["Tomorrow"]


def test_health_summary_keeps_only_present_values_including_zero() -> None:
    health = PlannerHealthSummary(
        sleep={"duration_hours": 7.2, "quality": "good"},
        resting_hr=52,
        body_battery=0,
        recent_activities=[{"name": "Run", "distance_km": 8.1}],
    )
    _prompt, data = _render(_dashboard(garmin_connected=True, health_summary=health))
    assert data["health_summary"] == {
        "sleep": {"duration_hours": 7.2, "quality": "good"},
        "resting_hr": 52,
        "body_battery": 0,
        "recent_activities": [{"name": "Run", "distance_km": 8.1}],
    }


def test_a_health_summary_with_no_values_is_omitted() -> None:
    _prompt, data = _render(_dashboard(health_summary=PlannerHealthSummary()))
    assert "health_summary" not in data


def test_sparse_dicts_missing_optional_keys_render_with_defaults() -> None:
    dashboard = {
        "days": [{"events": [{}], "tasks": [{}], "weather": {}}],
        "overdue_tasks": [{}],
        "health_summary": {},
    }
    _prompt, data = _render(dashboard)
    [day] = data["days"]
    assert day["day_name"] == "Unknown"
    assert day["events"][0]["summary"] == "(No title)"
    assert day["tasks"][0]["priority"] == 1
    assert data["overdue_tasks"][0]["content"] == ""
    assert "health_summary" not in data
