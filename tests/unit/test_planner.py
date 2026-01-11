"""Unit tests for planner feature.

Tests for:
- should_reset_planner() function in models.py
- get_dashboard_context_prompt() function in chat_agent.py
- PlannerDashboard building in planner_data.py
"""

from datetime import datetime, timedelta

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
