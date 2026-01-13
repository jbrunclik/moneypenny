"""Unit tests for planner feature.

Tests for:
- should_reset_planner() function in models.py
- get_dashboard_context_prompt() function in chat_agent.py
- PlannerDashboard building in planner_data.py
- refresh_planner_dashboard tool
"""

from datetime import datetime, timedelta
from typing import Any

from src.agent.chat_agent import get_dashboard_context_prompt, get_system_prompt
from src.db.models import User, should_reset_planner
from src.utils.planner_data import (
    PlannerDashboard,
    PlannerDay,
    PlannerEvent,
    PlannerTask,
    _format_event_for_dashboard,
    _format_task_for_dashboard,
    _get_day_name,
    _parse_date,
    _parse_datetime,
)


class TestShouldResetPlanner:
    """Tests for the should_reset_planner function."""

    def test_first_use_no_reset(self) -> None:
        """No reset should happen on first use (planner_last_reset_at is None)."""
        user = User(
            id="test-user",
            email="test@example.com",
            name="Test User",
            picture=None,
            created_at=datetime.now(),
            planner_last_reset_at=None,
        )
        assert should_reset_planner(user) is False

    def test_same_day_after_4am_no_reset(self) -> None:
        """No reset if last reset was today after 4am and it's still today."""
        # Simulate: last reset was today at 10:00 AM, now is today at 3:00 PM
        now = datetime.now().replace(hour=15, minute=0, second=0, microsecond=0)
        last_reset = now.replace(hour=10, minute=0)

        user = User(
            id="test-user",
            email="test@example.com",
            name="Test User",
            picture=None,
            created_at=datetime.now(),
            planner_last_reset_at=last_reset,
        )
        # This test depends on current time, so we can't test it directly
        # But we can test the logic by checking recent reset times
        # If reset happened today after 4am, and current hour >= 4, no reset
        if now.hour >= 4:
            assert should_reset_planner(user) is False

    def test_yesterday_after_4am_needs_reset(self) -> None:
        """Reset should trigger if last reset was yesterday and it's now after 4am today."""
        now = datetime.now()
        # Ensure we're testing after 4am
        if now.hour < 4:
            # If before 4am, adjust the test to work correctly
            # Last reset was 2 days ago (before yesterday's 4am)
            last_reset = now - timedelta(days=2)
        else:
            # Normal case: last reset was yesterday morning
            last_reset = (now - timedelta(days=1)).replace(hour=10, minute=0)

        user = User(
            id="test-user",
            email="test@example.com",
            name="Test User",
            picture=None,
            created_at=datetime.now(),
            planner_last_reset_at=last_reset,
        )
        assert should_reset_planner(user) is True

    def test_old_reset_needs_update(self) -> None:
        """Reset should trigger if last reset was several days ago."""
        now = datetime.now()
        # Last reset was 5 days ago
        last_reset = now - timedelta(days=5)

        user = User(
            id="test-user",
            email="test@example.com",
            name="Test User",
            picture=None,
            created_at=datetime.now(),
            planner_last_reset_at=last_reset,
        )
        assert should_reset_planner(user) is True

    def test_before_4am_uses_previous_day_cutoff(self) -> None:
        """Before 4am, the 4am cutoff should be from the previous day."""
        # This tests the edge case where it's 2am today
        # The 4am cutoff should be yesterday's 4am
        # So if last reset was yesterday at 5am, no reset needed (after yesterday's 4am)
        # But if last reset was 2 days ago, reset is needed
        pass  # This is hard to test without mocking datetime.now()


class TestGetDayName:
    """Tests for _get_day_name helper function."""

    def test_today(self) -> None:
        """Test that today returns 'Today'."""
        now = datetime.now()
        assert _get_day_name(now, now) == "Today"

    def test_tomorrow(self) -> None:
        """Test that tomorrow returns 'Tomorrow'."""
        now = datetime.now()
        tomorrow = now + timedelta(days=1)
        assert _get_day_name(tomorrow, now) == "Tomorrow"

    def test_weekday(self) -> None:
        """Test that other days return weekday name."""
        now = datetime.now()
        future = now + timedelta(days=3)
        result = _get_day_name(future, now)
        assert result == future.strftime("%A")


class TestParseDate:
    """Tests for _parse_date helper function."""

    def test_valid_date(self) -> None:
        """Test parsing a valid date string."""
        result = _parse_date("2024-12-25")
        assert result is not None
        assert result.year == 2024
        assert result.month == 12
        assert result.day == 25

    def test_none_returns_none(self) -> None:
        """Test that None input returns None."""
        assert _parse_date(None) is None

    def test_invalid_format_returns_none(self) -> None:
        """Test that invalid format returns None."""
        assert _parse_date("25-12-2024") is None
        assert _parse_date("invalid") is None


class TestParseDatetime:
    """Tests for _parse_datetime helper function."""

    def test_iso_format(self) -> None:
        """Test parsing ISO datetime string."""
        result = _parse_datetime("2024-12-25T10:30:00")
        assert result is not None
        assert result.year == 2024
        assert result.month == 12
        assert result.day == 25
        assert result.hour == 10
        assert result.minute == 30

    def test_z_suffix(self) -> None:
        """Test parsing datetime with Z suffix (UTC)."""
        result = _parse_datetime("2024-12-25T10:30:00Z")
        assert result is not None
        assert result.year == 2024

    def test_none_returns_none(self) -> None:
        """Test that None input returns None."""
        assert _parse_datetime(None) is None


class TestFormatTaskForDashboard:
    """Tests for _format_task_for_dashboard helper function."""

    def test_basic_task(self) -> None:
        """Test formatting a basic task."""
        task_data = {
            "id": "task-123",
            "content": "Buy groceries",
            "description": "Get milk and eggs",
            "priority": 2,
            "labels": ["shopping"],
        }
        result = _format_task_for_dashboard(task_data)
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
        result = _format_task_for_dashboard(task_data)
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
        result = _format_task_for_dashboard(task_data, section_map, project_map)
        assert result.project_name == "Work"
        assert result.section_name == "Code Review"


class TestFormatEventForDashboard:
    """Tests for _format_event_for_dashboard helper function."""

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
        result = _format_event_for_dashboard(event_data)
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
        result = _format_event_for_dashboard(event_data)
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
        result = _format_event_for_dashboard(event_data)
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
        from src.utils.planner_data import build_planner_dashboard

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

        import src.utils.planner_data

        original_fetch_calendar = src.utils.planner_data.fetch_calendar_dashboard_data
        original_fetch_todoist = src.utils.planner_data.fetch_todoist_dashboard_data

        try:
            src.utils.planner_data.fetch_calendar_dashboard_data = mock_fetch_calendar  # type: ignore[assignment]
            src.utils.planner_data.fetch_todoist_dashboard_data = mock_fetch_todoist  # type: ignore[assignment]

            # Mock datetime.now() to return a fixed date (2024-12-23)
            from unittest.mock import patch

            with patch("src.utils.planner_data.datetime") as mock_datetime:
                mock_datetime.now.return_value = datetime(2024, 12, 23, 10, 0, 0)
                mock_datetime.strptime = datetime.strptime
                mock_datetime.fromisoformat = datetime.fromisoformat
                mock_datetime.utcnow.return_value = datetime(2024, 12, 23, 10, 0, 0)

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
            src.utils.planner_data.fetch_calendar_dashboard_data = original_fetch_calendar
            src.utils.planner_data.fetch_todoist_dashboard_data = original_fetch_todoist

    def test_single_day_all_day_event_only_on_one_day(self) -> None:
        """Test that a single-day all-day event only appears on one day."""
        from src.utils.planner_data import build_planner_dashboard

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

        import src.utils.planner_data

        original_fetch_calendar = src.utils.planner_data.fetch_calendar_dashboard_data
        original_fetch_todoist = src.utils.planner_data.fetch_todoist_dashboard_data

        try:
            src.utils.planner_data.fetch_calendar_dashboard_data = mock_fetch_calendar  # type: ignore[assignment]
            src.utils.planner_data.fetch_todoist_dashboard_data = mock_fetch_todoist  # type: ignore[assignment]

            from unittest.mock import patch

            with patch("src.utils.planner_data.datetime") as mock_datetime:
                mock_datetime.now.return_value = datetime(2024, 12, 23, 10, 0, 0)
                mock_datetime.strptime = datetime.strptime
                mock_datetime.fromisoformat = datetime.fromisoformat
                mock_datetime.utcnow.return_value = datetime(2024, 12, 23, 10, 0, 0)

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
            src.utils.planner_data.fetch_calendar_dashboard_data = original_fetch_calendar
            src.utils.planner_data.fetch_todoist_dashboard_data = original_fetch_todoist

    def test_timed_event_not_duplicated(self) -> None:
        """Test that timed events (non-all-day) are not duplicated across days."""
        from src.utils.planner_data import build_planner_dashboard

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

        import src.utils.planner_data

        original_fetch_calendar = src.utils.planner_data.fetch_calendar_dashboard_data
        original_fetch_todoist = src.utils.planner_data.fetch_todoist_dashboard_data

        try:
            src.utils.planner_data.fetch_calendar_dashboard_data = mock_fetch_calendar  # type: ignore[assignment]
            src.utils.planner_data.fetch_todoist_dashboard_data = mock_fetch_todoist  # type: ignore[assignment]

            from unittest.mock import patch

            with patch("src.utils.planner_data.datetime") as mock_datetime:
                mock_datetime.now.return_value = datetime(2024, 12, 23, 10, 0, 0)
                mock_datetime.strptime = datetime.strptime
                mock_datetime.fromisoformat = datetime.fromisoformat
                mock_datetime.utcnow.return_value = datetime(2024, 12, 23, 10, 0, 0)

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
            src.utils.planner_data.fetch_calendar_dashboard_data = original_fetch_calendar
            src.utils.planner_data.fetch_todoist_dashboard_data = original_fetch_todoist


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
        assert "Error: Unable to refresh dashboard" in result
        assert "no active user context" in result

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
        assert "Error: No integrations connected" in result

    def test_tool_refreshes_dashboard_successfully(self, mocker: Any) -> None:
        """Test that the tool successfully refreshes the dashboard."""

        from src.agent.tools.planner import refresh_planner_dashboard
        from src.db.models import User
        from src.utils.planner_data import PlannerDashboard, PlannerDay, PlannerTask

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
        """Regression test: Verify calendar token refresh import works correctly.

        This test ensures the refresh_access_token import from src.auth.google_calendar
        works correctly when a user has calendar tokens that need refreshing.
        """
        from src.agent.tools.planner import refresh_planner_dashboard
        from src.db.models import User
        from src.utils.planner_data import PlannerDashboard

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

        # Mock refresh_access_token to return token data
        # This will fail if the import path is incorrect
        mock_refresh = mocker.patch(
            "src.auth.google_calendar.refresh_access_token",
            return_value={"access_token": "new-calendar-token", "refresh_token": "refresh-token"},
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

        # Verify refresh_access_token was called
        mock_refresh.assert_called_once_with("refresh-token")

        # Verify build_planner_dashboard was called with the new token
        mock_build.assert_called_once()
        call_kwargs = mock_build.call_args[1]
        assert call_kwargs["calendar_token"] == "new-calendar-token"

        # Check success message
        assert "Dashboard refreshed successfully" in result
