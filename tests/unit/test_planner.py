"""Unit tests for planner feature.

Tests for:
- should_reset_planner() function in models.py
- get_dashboard_context_prompt() function in chat_agent.py
- PlannerDashboard building in services/planner/dashboard.py
- refresh_planner_dashboard tool
"""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.agent.prompts import get_dashboard_context_prompt, get_system_prompt
from src.db.models import User, should_reset_planner
from src.services.planner.dates import day_name, local_date_of, parse_date
from src.services.planner.google_calendar import format_event
from src.services.planner.models import (
    PlannerDashboard,
    PlannerDay,
    PlannerEvent,
    PlannerTask,
)
from src.services.planner.todoist import format_task


def _planner_user(last_reset: datetime | None) -> User:
    return User(
        id="test-user",
        email="test@example.com",
        name="Test User",
        picture=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        planner_last_reset_at=last_reset,
    )


def _prague(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Europe/Prague"))


class TestShouldResetPlanner:
    """Tests for the should_reset_planner function (4am in APP_TIMEZONE)."""

    def test_first_use_no_reset(self) -> None:
        """No reset should happen on first use (planner_last_reset_at is None)."""
        assert should_reset_planner(_planner_user(None)) is False

    def test_same_day_after_4am_no_reset(self) -> None:
        """No reset if last reset was today after 4am and it's still today."""
        user = _planner_user(_prague(2026, 10, 20, 10, 0))
        assert should_reset_planner(user, now=_prague(2026, 10, 20, 15, 0)) is False

    def test_yesterday_after_4am_needs_reset(self) -> None:
        """Reset should trigger if last reset was yesterday and it's now after 4am today."""
        user = _planner_user(_prague(2026, 10, 19, 10, 0))
        assert should_reset_planner(user, now=_prague(2026, 10, 20, 4, 30)) is True

    def test_old_reset_needs_update(self) -> None:
        """Reset should trigger if last reset was several days ago."""
        user = _planner_user(_prague(2026, 10, 15, 10, 0))
        assert should_reset_planner(user, now=_prague(2026, 10, 20, 15, 0)) is True

    def test_before_4am_uses_previous_day_cutoff(self) -> None:
        """Before 4am, the 4am cutoff should be from the previous day."""
        two_am = _prague(2026, 10, 25, 2, 0)
        assert should_reset_planner(_planner_user(_prague(2026, 10, 24, 5, 0)), now=two_am) is False
        assert should_reset_planner(_planner_user(_prague(2026, 10, 23, 5, 0)), now=two_am) is True

    def test_cutoff_is_local_4am_whatever_the_utc_offset(self) -> None:
        """The day after the clocks went back (UTC+1) the cutoff is 03:00 UTC, in
        summer (UTC+2) 02:00 UTC - never a fixed UTC hour."""
        winter_now = datetime(2026, 10, 26, 3, 30, tzinfo=UTC)  # 04:30 in Prague
        assert (
            should_reset_planner(
                _planner_user(datetime(2026, 10, 26, 2, 30, tzinfo=UTC)), now=winter_now
            )
            is True
        )
        summer_now = datetime(2026, 7, 1, 2, 30, tzinfo=UTC)  # 04:30 in Prague
        assert (
            should_reset_planner(
                _planner_user(datetime(2026, 7, 1, 1, 30, tzinfo=UTC)), now=summer_now
            )
            is True
        )
        assert (
            should_reset_planner(
                _planner_user(datetime(2026, 7, 1, 2, 15, tzinfo=UTC)), now=summer_now
            )
            is False
        )


class TestGetDayName:
    """Tests for the day_name helper."""

    def test_today(self) -> None:
        """Test that today returns 'Today'."""
        today = date(2026, 10, 27)
        assert day_name(today, today) == "Today"

    def test_tomorrow(self) -> None:
        """Test that tomorrow returns 'Tomorrow'."""
        today = date(2026, 10, 27)
        assert day_name(today + timedelta(days=1), today) == "Tomorrow"

    def test_weekday(self) -> None:
        """Test that other days return weekday name."""
        assert day_name(date(2026, 10, 30), date(2026, 10, 27)) == "Friday"


class TestParseDate:
    """Tests for the parse_date helper."""

    def test_valid_date(self) -> None:
        """Test parsing a valid date string."""
        assert parse_date("2024-12-25") == date(2024, 12, 25)

    def test_none_returns_none(self) -> None:
        """Test that None input returns None."""
        assert parse_date(None) is None

    def test_invalid_format_returns_none(self) -> None:
        """Test that invalid format returns None."""
        assert parse_date("25-12-2024") is None
        assert parse_date("invalid") is None


class TestLocalDateOf:
    """Tests for the local_date_of helper (the APP_TIMEZONE date of a datetime)."""

    def test_offset_values_land_on_their_local_date(self) -> None:
        # yr.no forecast periods are UTC: 23:00Z is already the next day in Prague
        assert local_date_of("2024-12-25T23:00:00Z") == date(2024, 12, 26)
        assert local_date_of("2024-12-25T22:59:00+00:00") == date(2024, 12, 25)
        assert local_date_of("2024-12-25T00:30:00+01:00") == date(2024, 12, 25)

    def test_value_without_offset_keeps_its_date(self) -> None:
        assert local_date_of("2024-12-25T23:30:00") == date(2024, 12, 25)

    def test_none_and_garbage_return_none(self) -> None:
        assert local_date_of(None) is None
        assert local_date_of("not a date") is None


class TestFormatTaskForDashboard:
    """Tests for the format_task helper."""

    def test_basic_task(self) -> None:
        """Test formatting a basic task."""
        task_data = {
            "id": "task-123",
            "content": "Buy groceries",
            "description": "Get milk and eggs",
            "priority": 2,
            "labels": ["shopping"],
        }
        result = format_task(task_data)
        assert result.id == "task-123"
        assert result.content == "Buy groceries"
        assert result.description == "Get milk and eggs"
        assert result.priority == 2
        assert result.labels == ["shopping"]

    def test_task_with_due_date(self) -> None:
        """Test formatting a task with due date."""
        task_data = {
            "id": "task-123",
            "content": "Submit report",
            "due": {
                "date": "2024-12-25",
                "string": "Dec 25",
                "is_recurring": False,
            },
        }
        result = format_task(task_data)
        assert result.due_date == "2024-12-25"
        assert result.due_string == "Dec 25"
        assert result.is_recurring is False

    def test_task_with_project_and_section(self) -> None:
        """Test formatting a task with project and section names."""
        task_data = {
            "id": "task-123",
            "content": "Review PR",
            "project_id": "proj-1",
            "section_id": "sect-1",
        }
        project_map = {"proj-1": "Work"}
        section_map = {"sect-1": "Code Review"}
        result = format_task(task_data, section_map, project_map)
        assert result.project_name == "Work"
        assert result.section_name == "Code Review"


class TestFormatEventForDashboard:
    """Tests for the format_event helper."""

    def test_timed_event(self) -> None:
        """Test formatting a timed event."""
        event_data = {
            "id": "event-123",
            "summary": "Team Meeting",
            "description": "Weekly standup",
            "start": {"dateTime": "2024-12-25T10:00:00"},
            "end": {"dateTime": "2024-12-25T11:00:00"},
            "location": "Conference Room A",
        }
        result = format_event(event_data)
        assert result.id == "event-123"
        assert result.summary == "Team Meeting"
        assert result.start == "2024-12-25T10:00:00"
        assert result.end == "2024-12-25T11:00:00"
        assert result.is_all_day is False

    def test_all_day_event(self) -> None:
        """Test formatting an all-day event."""
        event_data = {
            "id": "event-456",
            "summary": "Holiday",
            "start": {"date": "2024-12-25"},
            "end": {"date": "2024-12-26"},
        }
        result = format_event(event_data)
        assert result.id == "event-456"
        assert result.summary == "Holiday"
        assert result.start_date == "2024-12-25"
        assert result.is_all_day is True

    def test_event_with_attendees(self) -> None:
        """Test formatting an event with attendees."""
        event_data = {
            "id": "event-789",
            "summary": "1:1 Meeting",
            "start": {"dateTime": "2024-12-25T14:00:00"},
            "end": {"dateTime": "2024-12-25T14:30:00"},
            "attendees": [
                {"email": "alice@example.com", "responseStatus": "accepted", "self": True},
                {"email": "bob@example.com", "responseStatus": "tentative"},
            ],
        }
        result = format_event(event_data)
        assert len(result.attendees) == 2
        assert result.attendees[0]["email"] == "alice@example.com"


class TestGetDashboardContextPrompt:
    """Tests for get_dashboard_context_prompt function (JSON format)."""

    def test_empty_dashboard(self) -> None:
        """Test formatting an empty dashboard."""
        import json

        dashboard = {
            "days": [],
            "overdue_tasks": [],
            "todoist_connected": False,
            "calendar_connected": False,
            "server_time": "2024-12-25T10:00:00",
        }
        result = get_dashboard_context_prompt(dashboard)
        assert "# Current Schedule Overview" in result
        assert "```json" in result

        # Parse the JSON from the result
        json_start = result.find("```json\n") + len("```json\n")
        json_end = result.find("\n```", json_start)
        json_str = result[json_start:json_end]
        data = json.loads(json_str)

        assert data["integrations"]["todoist_connected"] is False
        assert data["integrations"]["calendar_connected"] is False
        assert data["overdue_tasks"] == []
        assert data["days"] == []

    def test_connected_integrations(self) -> None:
        """Test dashboard with connected integrations."""
        import json

        dashboard = {
            "days": [],
            "overdue_tasks": [],
            "todoist_connected": True,
            "calendar_connected": True,
            "server_time": "2024-12-25T10:00:00",
        }
        result = get_dashboard_context_prompt(dashboard)

        # Parse JSON
        json_start = result.find("```json\n") + len("```json\n")
        json_end = result.find("\n```", json_start)
        data = json.loads(result[json_start:json_end])

        assert data["integrations"]["todoist_connected"] is True
        assert data["integrations"]["calendar_connected"] is True

    def test_overdue_tasks(self) -> None:
        """Test dashboard with overdue tasks."""
        import json

        dashboard = {
            "days": [],
            "overdue_tasks": [
                {
                    "id": "task-1",
                    "content": "Urgent task",
                    "priority": 4,
                    "project_name": "Work",
                    "due_string": "Dec 20",
                },
                {
                    "id": "task-2",
                    "content": "Normal task",
                    "priority": 1,
                },
            ],
            "todoist_connected": True,
            "calendar_connected": False,
            "server_time": "2024-12-25T10:00:00",
        }
        result = get_dashboard_context_prompt(dashboard)

        # Parse JSON
        json_start = result.find("```json\n") + len("```json\n")
        json_end = result.find("\n```", json_start)
        data = json.loads(result[json_start:json_end])

        assert len(data["overdue_tasks"]) == 2
        assert data["overdue_tasks"][0]["content"] == "Urgent task"
        assert data["overdue_tasks"][0]["priority"] == 4
        assert data["overdue_tasks"][0]["project_name"] == "Work"
        assert data["overdue_tasks"][0]["due_string"] == "Dec 20"
        assert data["overdue_tasks"][1]["content"] == "Normal task"
        assert data["overdue_tasks"][1]["priority"] == 1

    def test_day_with_events_and_tasks(self) -> None:
        """Test dashboard with events and tasks on a day."""
        import json

        dashboard = {
            "days": [
                {
                    "date": "2024-12-25",
                    "day_name": "Today",
                    "events": [
                        {
                            "id": "event-1",
                            "summary": "Morning Meeting",
                            "start": "2024-12-25T09:00:00",
                            "is_all_day": False,
                            "location": "Room A",
                        },
                    ],
                    "tasks": [
                        {
                            "id": "task-1",
                            "content": "Review code",
                            "priority": 3,
                            "project_name": "Development",
                        },
                    ],
                }
            ],
            "overdue_tasks": [],
            "todoist_connected": True,
            "calendar_connected": True,
            "server_time": "2024-12-25T10:00:00",
        }
        result = get_dashboard_context_prompt(dashboard)

        # Parse JSON
        json_start = result.find("```json\n") + len("```json\n")
        json_end = result.find("\n```", json_start)
        data = json.loads(result[json_start:json_end])

        assert len(data["days"]) == 1
        assert data["days"][0]["day_name"] == "Today"
        assert data["days"][0]["date"] == "2024-12-25"
        assert len(data["days"][0]["events"]) == 1
        assert data["days"][0]["events"][0]["summary"] == "Morning Meeting"
        assert data["days"][0]["events"][0]["location"] == "Room A"
        assert len(data["days"][0]["tasks"]) == 1
        assert data["days"][0]["tasks"][0]["content"] == "Review code"
        assert data["days"][0]["tasks"][0]["priority"] == 3

    def test_all_day_event_formatting(self) -> None:
        """Test all-day event formatting."""
        import json

        dashboard = {
            "days": [
                {
                    "date": "2024-12-25",
                    "day_name": "Today",
                    "events": [
                        {
                            "id": "event-1",
                            "summary": "Holiday",
                            "is_all_day": True,
                        },
                    ],
                    "tasks": [],
                }
            ],
            "overdue_tasks": [],
            "todoist_connected": False,
            "calendar_connected": True,
            "server_time": "2024-12-25T10:00:00",
        }
        result = get_dashboard_context_prompt(dashboard)

        # Parse JSON
        json_start = result.find("```json\n") + len("```json\n")
        json_end = result.find("\n```", json_start)
        data = json.loads(result[json_start:json_end])

        assert data["days"][0]["events"][0]["summary"] == "Holiday"
        assert data["days"][0]["events"][0]["is_all_day"] is True

    def test_error_messages(self) -> None:
        """Test dashboard with error messages."""
        import json

        dashboard = {
            "days": [],
            "overdue_tasks": [],
            "todoist_connected": True,
            "calendar_connected": True,
            "todoist_error": "Token expired",
            "calendar_error": "API limit reached",
            "server_time": "2024-12-25T10:00:00",
        }
        result = get_dashboard_context_prompt(dashboard)

        # Parse JSON
        json_start = result.find("```json\n") + len("```json\n")
        json_end = result.find("\n```", json_start)
        data = json.loads(result[json_start:json_end])

        assert data["integrations"]["todoist_error"] == "Token expired"
        assert data["integrations"]["calendar_error"] == "API limit reached"


class TestGetSystemPromptWithPlanning:
    """Tests for get_system_prompt with is_planning parameter."""

    def test_planning_mode_includes_planner_prompt(self) -> None:
        """Test that planning mode includes PLANNER_SYSTEM_PROMPT."""
        result = get_system_prompt(
            with_tools=True,
            is_planning=True,
        )
        assert "Planner Mode - Daily Planning Session" in result
        assert "Executive Strategist" in result

    def test_planning_mode_with_dashboard(self) -> None:
        """Test that planning mode includes dashboard context."""
        dashboard = {
            "days": [
                {
                    "date": "2024-12-25",
                    "day_name": "Today",
                    "events": [],
                    "tasks": [{"id": "1", "content": "Test task", "priority": 1}],
                }
            ],
            "overdue_tasks": [],
            "todoist_connected": True,
            "calendar_connected": False,
            "server_time": "2024-12-25T10:00:00",
        }
        result = get_system_prompt(
            with_tools=True,
            is_planning=True,
            dashboard_data=dashboard,
        )
        assert "Current Schedule Overview" in result
        assert "Test task" in result

    def test_regular_mode_excludes_planner_prompt(self) -> None:
        """Test that regular mode does NOT include PLANNER_SYSTEM_PROMPT."""
        result = get_system_prompt(
            with_tools=True,
            is_planning=False,
        )
        assert "Planner Mode - Daily Planning Session" not in result

    def test_planning_mode_still_includes_productivity_tools(self) -> None:
        """Test that planning mode includes productivity tools documentation."""
        result = get_system_prompt(
            with_tools=True,
            is_planning=True,
            anonymous_mode=False,
        )
        assert "Strategic Productivity Partner" in result
        assert "todoist" in result.lower()


class TestPlannerDataclasses:
    """Tests for planner dataclasses."""

    def test_planner_task_defaults(self) -> None:
        """Test PlannerTask default values."""
        task = PlannerTask(id="1", content="Test")
        assert task.description == ""
        assert task.due_date is None
        assert task.priority == 1
        assert task.labels == []
        assert task.is_recurring is False

    def test_planner_event_defaults(self) -> None:
        """Test PlannerEvent default values."""
        event = PlannerEvent(id="1", summary="Test")
        assert event.description is None
        assert event.is_all_day is False
        assert event.attendees == []

    def test_planner_day_defaults(self) -> None:
        """Test PlannerDay default values."""
        day = PlannerDay(date="2024-12-25", day_name="Today")
        assert day.events == []
        assert day.tasks == []

    def test_planner_dashboard_defaults(self) -> None:
        """Test PlannerDashboard default values."""
        dashboard = PlannerDashboard(days=[])
        assert dashboard.overdue_tasks == []
        assert dashboard.todoist_connected is False
        assert dashboard.calendar_connected is False
        assert dashboard.todoist_error is None
        assert dashboard.calendar_error is None


class TestMultiDayEventHandling:
    """Tests for multi-day event handling in build_planner_dashboard."""

    def test_multi_day_event_appears_on_all_days(self) -> None:
        """Test that a multi-day all-day event appears on every day it spans."""
        from src.services.planner.dashboard import build_planner_dashboard

        # Mock fetch functions to return a 3-day all-day event (Mon-Wed)
        def mock_fetch_calendar(*args: Any, **kwargs: Any) -> tuple[list[PlannerEvent], None]:
            """Return a single multi-day event spanning 3 days."""
            event = PlannerEvent(
                id="event-multiday",
                summary="Company Offsite",
                start_date="2024-12-23",  # Monday
                end_date="2024-12-26",  # Thursday (exclusive, so event ends Wed)
                is_all_day=True,
            )
            return [event], None

        def mock_fetch_todoist(
            *args: Any, **kwargs: Any
        ) -> tuple[list[PlannerTask], list[PlannerTask], None]:
            """Return no tasks."""
            return [], [], None

        import src.services.planner.dashboard

        original_fetch_calendar = src.services.planner.dashboard.fetch_calendar_dashboard_data
        original_fetch_todoist = src.services.planner.dashboard.fetch_todoist_dashboard_data

        try:
            src.services.planner.dashboard.fetch_calendar_dashboard_data = mock_fetch_calendar  # type: ignore[assignment]
            src.services.planner.dashboard.fetch_todoist_dashboard_data = mock_fetch_todoist  # type: ignore[assignment]

            # Monday 2024-12-23, 10:00 in Prague
            from unittest.mock import patch

            with patch("src.utils.clock._now", return_value=datetime(2024, 12, 23, 9, tzinfo=UTC)):
                dashboard = build_planner_dashboard(
                    todoist_token=None,
                    calendar_token="fake-token",
                    user_id=None,
                    force_refresh=True,
                )

            # Verify the event appears on days 0, 1, 2 (Mon, Tue, Wed)
            # but NOT on day 3 (Thu) since end_date is exclusive
            assert len(dashboard.days) == 7

            # Monday (2024-12-23) - should have the event
            assert len(dashboard.days[0].events) == 1
            assert dashboard.days[0].events[0].summary == "Company Offsite"
            assert dashboard.days[0].date == "2024-12-23"

            # Tuesday (2024-12-24) - should have the event
            assert len(dashboard.days[1].events) == 1
            assert dashboard.days[1].events[0].summary == "Company Offsite"
            assert dashboard.days[1].date == "2024-12-24"

            # Wednesday (2024-12-25) - should have the event
            assert len(dashboard.days[2].events) == 1
            assert dashboard.days[2].events[0].summary == "Company Offsite"
            assert dashboard.days[2].date == "2024-12-25"

            # Thursday (2024-12-26) - should NOT have the event (end_date is exclusive)
            assert len(dashboard.days[3].events) == 0
            assert dashboard.days[3].date == "2024-12-26"

        finally:
            # Restore original functions
            src.services.planner.dashboard.fetch_calendar_dashboard_data = original_fetch_calendar
            src.services.planner.dashboard.fetch_todoist_dashboard_data = original_fetch_todoist

    def test_single_day_all_day_event_only_on_one_day(self) -> None:
        """Test that a single-day all-day event only appears on one day."""
        from src.services.planner.dashboard import build_planner_dashboard

        def mock_fetch_calendar(*args: Any, **kwargs: Any) -> tuple[list[PlannerEvent], None]:
            """Return a single-day all-day event."""
            event = PlannerEvent(
                id="event-singleday",
                summary="Birthday",
                start_date="2024-12-25",  # Wednesday
                end_date="2024-12-26",  # Thursday (exclusive, so just Wednesday)
                is_all_day=True,
            )
            return [event], None

        def mock_fetch_todoist(
            *args: Any, **kwargs: Any
        ) -> tuple[list[PlannerTask], list[PlannerTask], None]:
            """Return no tasks."""
            return [], [], None

        import src.services.planner.dashboard

        original_fetch_calendar = src.services.planner.dashboard.fetch_calendar_dashboard_data
        original_fetch_todoist = src.services.planner.dashboard.fetch_todoist_dashboard_data

        try:
            src.services.planner.dashboard.fetch_calendar_dashboard_data = mock_fetch_calendar  # type: ignore[assignment]
            src.services.planner.dashboard.fetch_todoist_dashboard_data = mock_fetch_todoist  # type: ignore[assignment]

            from unittest.mock import patch

            with patch("src.utils.clock._now", return_value=datetime(2024, 12, 23, 9, tzinfo=UTC)):
                dashboard = build_planner_dashboard(
                    todoist_token=None,
                    calendar_token="fake-token",
                    user_id=None,
                    force_refresh=True,
                )

            # Event should only appear on Wednesday (day 2)
            assert len(dashboard.days[0].events) == 0  # Monday
            assert len(dashboard.days[1].events) == 0  # Tuesday
            assert len(dashboard.days[2].events) == 1  # Wednesday
            assert dashboard.days[2].events[0].summary == "Birthday"
            assert len(dashboard.days[3].events) == 0  # Thursday

        finally:
            src.services.planner.dashboard.fetch_calendar_dashboard_data = original_fetch_calendar
            src.services.planner.dashboard.fetch_todoist_dashboard_data = original_fetch_todoist

    def test_timed_event_not_duplicated(self) -> None:
        """Test that timed events (non-all-day) are not duplicated across days."""
        from src.services.planner.dashboard import build_planner_dashboard

        def mock_fetch_calendar(*args: Any, **kwargs: Any) -> tuple[list[PlannerEvent], None]:
            """Return a timed event."""
            event = PlannerEvent(
                id="event-timed",
                summary="Team Meeting",
                start="2024-12-23T14:00:00",
                end="2024-12-23T15:00:00",
                is_all_day=False,
            )
            return [event], None

        def mock_fetch_todoist(
            *args: Any, **kwargs: Any
        ) -> tuple[list[PlannerTask], list[PlannerTask], None]:
            """Return no tasks."""
            return [], [], None

        import src.services.planner.dashboard

        original_fetch_calendar = src.services.planner.dashboard.fetch_calendar_dashboard_data
        original_fetch_todoist = src.services.planner.dashboard.fetch_todoist_dashboard_data

        try:
            src.services.planner.dashboard.fetch_calendar_dashboard_data = mock_fetch_calendar  # type: ignore[assignment]
            src.services.planner.dashboard.fetch_todoist_dashboard_data = mock_fetch_todoist  # type: ignore[assignment]

            from unittest.mock import patch

            with patch("src.utils.clock._now", return_value=datetime(2024, 12, 23, 9, tzinfo=UTC)):
                dashboard = build_planner_dashboard(
                    todoist_token=None,
                    calendar_token="fake-token",
                    user_id=None,
                    force_refresh=True,
                )

            # Timed event should only appear once on the day it occurs
            assert len(dashboard.days[0].events) == 1  # Monday - has the event
            assert dashboard.days[0].events[0].summary == "Team Meeting"
            assert len(dashboard.days[1].events) == 0  # Tuesday - no events
            assert len(dashboard.days[2].events) == 0  # Wednesday - no events

        finally:
            src.services.planner.dashboard.fetch_calendar_dashboard_data = original_fetch_calendar
            src.services.planner.dashboard.fetch_todoist_dashboard_data = original_fetch_todoist


class TestRefreshPlannerDashboardTool:
    """Tests for the refresh_planner_dashboard tool."""

    def test_import_refresh_access_token(self) -> None:
        """Regression test: Verify that refresh_access_token can be imported correctly.

        This test catches import errors like 'No module named src.auth.google'
        which should be 'src.auth.google_calendar'.
        """
        # This will fail if the import path in planner.py is incorrect
        from src.auth.google_calendar import refresh_access_token

        # Verify the function is callable
        assert callable(refresh_access_token)

    def test_tool_requires_user_context(self) -> None:
        """Test that the tool returns an error when no user context is set."""
        from src.agent.tools.context import set_conversation_context
        from src.agent.tools.planner import refresh_planner_dashboard

        # Clear any existing context
        set_conversation_context(None, None)

        # Call the tool without setting user context
        result = refresh_planner_dashboard.invoke({})
        error = json.loads(result)
        assert "no active user context" in error["error"]
        assert error["retriable"] is False

    def test_tool_requires_integrations(self, mocker: Any) -> None:
        """Test that the tool returns an error when no integrations are connected."""
        from src.agent.tools.planner import refresh_planner_dashboard
        from src.db.models import User

        # Mock get_conversation_context to return a user_id
        mocker.patch(
            "src.agent.tools.planner.get_conversation_context", return_value=("conv-id", "user-id")
        )

        # Mock db.get_user_by_id to return a user with no integrations
        mock_user = User(
            id="user-id",
            email="test@example.com",
            name="Test User",
            picture=None,
            created_at=datetime.now(),
            todoist_access_token=None,
            google_calendar_access_token=None,
        )
        mocker.patch("src.agent.tools.planner.db.get_user_by_id", return_value=mock_user)

        # Call the tool
        result = refresh_planner_dashboard.invoke({})
        assert json.loads(result)["error"].startswith("No integrations connected")

    def test_tool_refreshes_dashboard_successfully(self, mocker: Any) -> None:
        """Test that the tool successfully refreshes the dashboard."""

        from src.agent.tools.planner import refresh_planner_dashboard
        from src.db.models import User
        from src.services.planner.models import PlannerDashboard, PlannerDay, PlannerTask

        # Mock get_conversation_context to return a user_id
        mocker.patch(
            "src.agent.tools.planner.get_conversation_context", return_value=("conv-id", "user-id")
        )

        # Mock db.get_user_by_id to return a user with Todoist connected
        mock_user = User(
            id="user-id",
            email="test@example.com",
            name="Test User",
            picture=None,
            created_at=datetime.now(),
            todoist_access_token="fake-token",
            google_calendar_access_token=None,
        )
        mocker.patch("src.agent.tools.planner.db.get_user_by_id", return_value=mock_user)

        # Mock build_planner_dashboard to return test data
        mock_dashboard = PlannerDashboard(
            days=[
                PlannerDay(
                    date="2024-12-25",
                    day_name="Today",
                    tasks=[
                        PlannerTask(
                            id="task-1",
                            content="Test task",
                            priority=4,
                        )
                    ],
                )
            ],
            overdue_tasks=[],
            todoist_connected=True,
            calendar_connected=False,
            server_time="2024-12-25T10:00:00",
        )

        mocker.patch(
            "src.agent.tools.planner.build_planner_dashboard",
            return_value=mock_dashboard,
        )

        # Call the tool
        result = refresh_planner_dashboard.invoke({})

        # Check result
        assert "Dashboard refreshed successfully" in result
        assert "1 task(s)" in result
        assert "0 calendar event(s)" in result

        # Note: We can't check the contextvar here because it's set within the tool execution
        # In real usage, the contextvar will be checked within the same execution context

    def test_tool_handles_errors_gracefully(self, mocker: Any) -> None:
        """Test that the tool handles API errors gracefully."""
        from src.agent.tools.planner import refresh_planner_dashboard
        from src.db.models import User

        # Mock get_conversation_context to return a user_id
        mocker.patch(
            "src.agent.tools.planner.get_conversation_context", return_value=("conv-id", "user-id")
        )

        # Mock db.get_user_by_id to return a user with Todoist connected
        mock_user = User(
            id="user-id",
            email="test@example.com",
            name="Test User",
            picture=None,
            created_at=datetime.now(),
            todoist_access_token="fake-token",
            google_calendar_access_token=None,
        )
        mocker.patch("src.agent.tools.planner.db.get_user_by_id", return_value=mock_user)

        # Mock build_planner_dashboard to raise an exception
        mocker.patch(
            "src.agent.tools.planner.build_planner_dashboard",
            side_effect=Exception("API error"),
        )

        # Call the tool
        result = refresh_planner_dashboard.invoke({})

        # Check that error is returned
        assert "Error refreshing dashboard" in result
        assert "API error" in result

    def test_tool_with_calendar_token_refresh(self, mocker: Any) -> None:
        """Regression test: Verify centralized calendar token helper is used.

        This test ensures planner uses get_valid_calendar_access_token from
        src.auth.google_calendar (the centralized helper) rather than calling
        refresh_access_token directly.
        """
        from src.agent.tools.planner import refresh_planner_dashboard
        from src.db.models import User
        from src.services.planner.models import PlannerDashboard

        # Mock get_conversation_context to return a user_id
        mocker.patch(
            "src.agent.tools.planner.get_conversation_context", return_value=("conv-id", "user-id")
        )

        # Mock db.get_user_by_id to return a user with both tokens
        mock_user = User(
            id="user-id",
            email="test@example.com",
            name="Test User",
            picture=None,
            created_at=datetime.now(),
            todoist_access_token="fake-todoist-token",
            google_calendar_access_token="old-calendar-token",
            google_calendar_refresh_token="refresh-token",
        )
        mocker.patch("src.agent.tools.planner.db.get_user_by_id", return_value=mock_user)

        # Mock the centralized helper - planner now delegates token refresh to this
        mock_get_token = mocker.patch(
            "src.agent.tools.planner.get_valid_calendar_access_token",
            return_value="new-calendar-token",
        )

        # Mock build_planner_dashboard to return empty dashboard
        mock_dashboard = PlannerDashboard(
            days=[],
            todoist_connected=True,
            calendar_connected=True,
            server_time="2024-12-25T10:00:00",
        )
        mock_build = mocker.patch(
            "src.agent.tools.planner.build_planner_dashboard",
            return_value=mock_dashboard,
        )

        # Call the tool
        result = refresh_planner_dashboard.invoke({})

        # Verify centralized helper was called with the user object
        mock_get_token.assert_called_once_with(mock_user)

        # Verify build_planner_dashboard was called with the new token
        mock_build.assert_called_once()
        call_kwargs = mock_build.call_args[1]
        assert call_kwargs["calendar_token"] == "new-calendar-token"

        # Check success message
        assert "Dashboard refreshed successfully" in result


class TestPlannerConversationIsUnique:
    """Each user has exactly one planner conversation, even under concurrent first opens."""

    def test_a_second_planner_row_is_rejected(self, test_database: Any, test_user: User) -> None:
        import sqlite3

        import pytest

        test_database.get_or_create_planner_conversation(test_user.id)
        # raises outside the connection, so the pool sees the error and rolls back
        with (
            pytest.raises(sqlite3.IntegrityError, match="UNIQUE"),
            test_database._pool.get_connection() as conn,
        ):
            conn.execute(
                """INSERT INTO conversations
                   (id, user_id, title, model, is_planning, created_at, updated_at)
                   VALUES ('dup', ?, 'Planner', 'm', 1, '2026-10-25', '2026-10-25')""",
                (test_user.id,),
            )

    def test_concurrent_first_opens_share_one_planner(
        self, test_database: Any, test_user: User, monkeypatch: Any
    ) -> None:
        """Two devices opening the planner at once: both look before either inserts."""
        import threading

        barrier = threading.Barrier(2, timeout=5)
        looked = threading.local()
        original = test_database._execute_with_timing

        def synced(conn: Any, query: str, params: tuple[Any, ...] = ()) -> Any:
            cursor = original(conn, query, params)
            is_lookup = query.startswith(
                "SELECT * FROM conversations WHERE user_id = ? AND is_planning = 1"
            )
            # Only each thread's first lookup waits (a follow-up re-read must not)
            if is_lookup and not getattr(looked, "done", False):
                looked.done = True
                barrier.wait()
            return cursor

        monkeypatch.setattr(test_database, "_execute_with_timing", synced)
        ids: list[str] = []

        def open_planner() -> None:
            ids.append(test_database.get_or_create_planner_conversation(test_user.id).id)

        threads = [threading.Thread(target=open_planner) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(ids) == 2 and ids[0] == ids[1]
        with test_database._pool.get_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM conversations WHERE user_id = ? AND is_planning = 1",
                (test_user.id,),
            ).fetchone()[0]
        assert count == 1


def test_migration_keeps_the_oldest_planner_when_duplicates_exist(tmp_path: Any) -> None:
    """Migration 0068 builds its unique index on a database that already has duplicates."""
    import sqlite3

    from yoyo import get_backend, read_migrations

    from src.db.models.base import MIGRATIONS_DIR

    db_path = tmp_path / "dupes.db"
    backend = get_backend(f"sqlite:///{db_path}")
    migrations = read_migrations(str(MIGRATIONS_DIR))
    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations.filter(lambda m: m.id < "0068")))
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO users (id, email, name, created_at) VALUES ('u', 'u@x', 'U', '2026-01-01')"
    )
    for conv_id, created in (("newer", "2026-10-02"), ("older", "2026-10-01")):
        conn.execute(
            """INSERT INTO conversations
               (id, user_id, title, model, is_planning, created_at, updated_at)
               VALUES (?, 'u', 'Planner', 'm', 1, ?, ?)""",
            (conv_id, created, created),
        )
    conn.execute(
        "INSERT INTO messages (id, conversation_id, role, content, created_at) "
        "VALUES ('m1', 'newer', 'user', 'kept', '2026-10-02')"
    )
    conn.commit()
    conn.close()

    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))

    conn = sqlite3.connect(db_path)
    planners = conn.execute("SELECT id FROM conversations WHERE is_planning = 1").fetchall()
    kept_message = conn.execute("SELECT conversation_id FROM messages WHERE id = 'm1'").fetchone()
    conn.close()
    assert planners == [("older",)]
    assert kept_message == ("newer",)
