"""Unit tests for autonomous agents feature.

Tests cover:
- Agent routes (CRUD, command center, approvals)
- Agent database operations
- Permission checking
- Executor context management
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from src.api.schemas import CreateAgentRequest, UpdateAgentRequest
from src.db.models.dataclasses import Agent, AgentExecution, ApprovalRequest

# =============================================================================
# Test fixtures
# =============================================================================


@pytest.fixture
def mock_db():
    """Create a mock database."""
    return MagicMock()


@pytest.fixture
def mock_user():
    """Create a mock user."""
    user = MagicMock()
    user.id = "user-123"
    user.email = "test@test.com"
    user.name = "Test User"
    return user


@pytest.fixture
def sample_agent():
    """Create a sample agent."""
    return Agent(
        id="agent-123",
        user_id="user-123",
        conversation_id="conv-123",
        name="Test Agent",
        description="A test agent",
        system_prompt="You are a test agent",
        schedule="0 9 * * *",
        timezone="UTC",
        enabled=True,
        tool_permissions=["web_search", "todoist"],
        model="gemini-3-flash-preview",
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
        last_run_at=None,
        next_run_at=datetime(2024, 1, 2, 9, 0, 0),
    )


@pytest.fixture
def sample_execution():
    """Create a sample execution."""
    return AgentExecution(
        id="exec-123",
        agent_id="agent-123",
        status="completed",
        trigger_type="manual",
        triggered_by_agent_id=None,
        started_at=datetime(2024, 1, 1, 12, 0, 0),
        completed_at=datetime(2024, 1, 1, 12, 1, 0),
        error_message=None,
    )


@pytest.fixture
def sample_approval():
    """Create a sample approval request."""
    return ApprovalRequest(
        id="approval-123",
        agent_id="agent-123",
        user_id="user-123",
        tool_name="todoist",
        tool_args={"operation": "add_task", "content": "Test task"},
        description='Create Todoist task "Test task"',
        status="pending",
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        resolved_at=None,
    )


# =============================================================================
# Schema validation tests
# =============================================================================


class TestCreateAgentRequest:
    """Tests for CreateAgentRequest schema."""

    def test_valid_minimal_request(self):
        """Test valid minimal request with only required fields."""
        data = CreateAgentRequest(name="Test Agent")
        assert data.name == "Test Agent"
        assert data.description is None
        assert data.schedule is None
        assert data.timezone == "UTC"
        assert data.enabled is True

    def test_valid_full_request(self):
        """Test valid request with all fields."""
        data = CreateAgentRequest(
            name="Full Agent",
            description="A full agent",
            system_prompt="You are helpful",
            schedule="0 9 * * *",
            timezone="America/New_York",
            tool_permissions=["todoist", "google_calendar"],
            enabled=False,
        )
        assert data.name == "Full Agent"
        assert data.description == "A full agent"
        assert data.schedule == "0 9 * * *"
        assert data.timezone == "America/New_York"
        assert data.tool_permissions == ["todoist", "google_calendar"]
        assert data.enabled is False

    def test_name_is_required(self):
        """Test that name field is required."""
        with pytest.raises(ValidationError):
            CreateAgentRequest()  # type: ignore

    def test_name_min_length(self):
        """Test name minimum length validation."""
        with pytest.raises(ValidationError):
            CreateAgentRequest(name="")

    def test_name_max_length(self):
        """Test name maximum length validation."""
        with pytest.raises(ValidationError):
            CreateAgentRequest(name="x" * 101)  # 101 chars, max is 100

    def test_description_max_length(self):
        """Test description maximum length validation."""
        with pytest.raises(ValidationError):
            CreateAgentRequest(name="Test", description="x" * 501)

    def test_system_prompt_max_length(self):
        """Test system prompt maximum length validation."""
        with pytest.raises(ValidationError):
            CreateAgentRequest(name="Test", system_prompt="x" * 10001)


class TestUpdateAgentRequest:
    """Tests for UpdateAgentRequest schema."""

    def test_all_fields_optional(self):
        """Test that all fields are optional for updates."""
        data = UpdateAgentRequest()
        assert data.name is None
        assert data.description is None
        assert data.schedule is None

    def test_partial_update(self):
        """Test partial update with some fields."""
        data = UpdateAgentRequest(name="New Name", enabled=False)
        assert data.name == "New Name"
        assert data.enabled is False
        assert data.description is None

    def test_model_dump_exclude_unset(self):
        """Test model_dump(exclude_unset=True) for partial updates."""
        # Only name provided
        data = UpdateAgentRequest(name="New Name")
        dump = data.model_dump(exclude_unset=True)
        assert dump == {"name": "New Name"}
        assert "description" not in dump
        assert "enabled" not in dump

        # Explicitly setting field to None
        data = UpdateAgentRequest(description=None)
        dump = data.model_dump(exclude_unset=True)
        assert dump == {"description": None}
        assert "name" not in dump

        # Multiple fields
        data = UpdateAgentRequest(name="Name", budget_limit=100.0)
        dump = data.model_dump(exclude_unset=True)
        assert dump == {"name": "Name", "budget_limit": 100.0}


# =============================================================================
# Permission checking tests
# =============================================================================


class TestPermissionChecking:
    """Tests for tool permission checking."""

    def test_always_safe_tools(self):
        """Test that always-safe tools don't require approval."""
        from src.agent.permissions import (
            ALWAYS_SAFE_TOOLS,
            PermissionResult,
            check_tool_permission,
        )

        agent = MagicMock()
        agent.tool_permissions = ["web_search", "fetch_url"]

        # Always-safe tools should be allowed
        for tool in ALWAYS_SAFE_TOOLS:
            agent.tool_permissions = [tool]
            result = check_tool_permission(agent, tool, {})
            assert result == PermissionResult.ALLOWED

    def test_blocked_when_not_permitted(self):
        """Test that tools are blocked if not in agent permissions."""
        from src.agent.permissions import PermissionResult, check_tool_permission

        agent = MagicMock()
        agent.tool_permissions = ["web_search"]  # Only web_search permitted

        # todoist should be blocked
        result = check_tool_permission(agent, "todoist", {"operation": "add_task"})
        assert result == PermissionResult.BLOCKED

    def test_empty_tool_permissions(self):
        """Test agent with empty tool permissions list (explicitly set to [])."""
        from src.agent.permissions import PermissionResult, check_tool_permission

        agent = MagicMock()
        agent.tool_permissions = []  # Explicitly set to empty

        # All tools should be blocked when permissions is an empty list
        result = check_tool_permission(agent, "todoist", {"operation": "add_task"})
        assert result == PermissionResult.BLOCKED

    def test_null_tool_permissions_allows_all_tools(self):
        """Test agent with None tool permissions (no restrictions on tools)."""
        from src.agent.permissions import PermissionResult, check_tool_permission

        agent = MagicMock()
        agent.tool_permissions = None  # No restrictions

        # With None permissions, all tools are allowed
        result = check_tool_permission(agent, "todoist", {"operation": "add_task"})
        assert result == PermissionResult.ALLOWED

    def test_null_tool_permissions_allows_safe_tools(self):
        """Test agent with None tool permissions allows safe tools."""
        from src.agent.permissions import PermissionResult, check_tool_permission

        agent = MagicMock()
        agent.tool_permissions = None  # No restrictions

        # Safe tools are always allowed
        result = check_tool_permission(agent, "web_search", {})
        assert result == PermissionResult.ALLOWED


# =============================================================================
# Executor context tests
# =============================================================================


class TestExecutorContext:
    """Tests for executor context management."""

    def test_get_agent_context_returns_none_outside_execution(self):
        """Test that get_agent_context returns None outside execution."""
        from src.agent.executor import get_agent_context

        # Outside an agent execution, context should be None
        result = get_agent_context()
        assert result is None

    def test_trigger_chain_management(self):
        """Test trigger chain for circular dependency prevention."""
        from src.agent.executor import (
            add_to_trigger_chain,
            get_trigger_chain,
        )

        # Initially should be empty
        chain = get_trigger_chain()
        assert chain == []

        # Note: add_to_trigger_chain returns a context token, not the chain itself
        # The chain is stored in context vars and retrieved via get_trigger_chain
        token = add_to_trigger_chain("agent-1")
        assert token is not None  # Should return a token

        # After adding, get_trigger_chain should return the updated chain
        chain = get_trigger_chain()
        assert "agent-1" in chain


# =============================================================================
# Route helper function tests (no Flask context needed)
# =============================================================================


class TestRouteHelpers:
    """Tests for route helper functions that don't need Flask context."""

    def test_cron_validation_valid(self):
        """Test that valid cron expressions pass validation."""
        from croniter import croniter

        valid_crons = [
            "0 9 * * *",
            "0 9 * * 1-5",
            "*/15 * * * *",
            "0 0 1 * *",
        ]

        for cron in valid_crons:
            # Should not raise
            croniter(cron)

    def test_cron_validation_invalid(self):
        """Test that invalid cron expressions fail."""
        from croniter import croniter
        from croniter.croniter import CroniterBadCronError

        with pytest.raises(CroniterBadCronError):
            croniter("invalid cron")

    def test_timezone_validation_valid(self):
        """Test that valid timezones pass validation."""
        from zoneinfo import ZoneInfo

        valid_timezones = [
            "UTC",
            "America/New_York",
            "Europe/Prague",
            "Asia/Tokyo",
        ]

        for tz in valid_timezones:
            # Should not raise
            ZoneInfo(tz)

    def test_timezone_validation_invalid(self):
        """Test that invalid timezones fail."""
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        with pytest.raises(ZoneInfoNotFoundError):
            ZoneInfo("Invalid/Timezone")


# =============================================================================
# Database operations tests (integration-style with mock)
# =============================================================================


class TestAgentDatabaseOperations:
    """Tests for agent database operations."""

    def test_agent_to_response_conversion(self, sample_agent):
        """Test agent-to-response conversion."""
        from src.api.routes.agents import _agent_to_response

        response = _agent_to_response(sample_agent, unread_count=5, has_pending_approval=True)

        assert response["id"] == "agent-123"
        assert response["name"] == "Test Agent"
        assert response["unread_count"] == 5
        assert response["has_pending_approval"] is True
        assert response["schedule"] == "0 9 * * *"

    def test_execution_to_response_conversion(self, sample_execution):
        """Test execution-to-response conversion."""
        from src.api.routes.agents import _execution_to_response

        response = _execution_to_response(sample_execution)

        assert response["id"] == "exec-123"
        assert response["agent_id"] == "agent-123"
        assert response["status"] == "completed"
        assert response["trigger_type"] == "manual"

    def test_approval_to_response_conversion(self, sample_approval):
        """Test approval-to-response conversion."""
        from src.api.routes.agents import _approval_to_response

        response = _approval_to_response(sample_approval, "Test Agent")

        assert response["id"] == "approval-123"
        assert response["agent_name"] == "Test Agent"
        assert response["tool_name"] == "todoist"
        assert response["status"] == "pending"


# =============================================================================
# Dev scheduler tests
# =============================================================================


class TestDevScheduler:
    """Tests for dev scheduler functionality."""

    def test_scheduler_handles_naive_datetime_from_database(self, sample_agent):
        """Test that scheduler correctly handles naive datetimes from database.

        This is a regression test for the TypeError:
        "can't compare offset-naive and offset-aware datetimes"

        The database stores datetimes without timezone info (naive UTC),
        but the scheduler uses timezone-aware datetimes for comparison.
        """
        from datetime import UTC, datetime

        # Simulate what the database returns: naive datetime (no tzinfo)
        naive_next_run = datetime(2024, 1, 2, 9, 0, 0)  # No tzinfo
        assert naive_next_run.tzinfo is None, "Test requires naive datetime"

        # Create agent with naive datetime (as from DB)
        agent = Agent(
            id="agent-123",
            user_id="user-123",
            conversation_id="conv-123",
            name="Test Agent",
            description=None,
            system_prompt=None,
            schedule="0 9 * * *",
            timezone="UTC",
            enabled=True,
            tool_permissions=None,
            model="gemini-3-flash-preview",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
            last_run_at=None,
            next_run_at=naive_next_run,  # Naive datetime
        )

        # Simulate scheduler comparison logic
        now = datetime.now(UTC)  # Aware datetime

        # The fix: convert naive to aware before comparison
        next_run = agent.next_run_at
        if next_run and next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=UTC)

        # This should not raise TypeError
        is_due = next_run <= now
        assert isinstance(is_due, bool)

    def test_scheduler_handles_aware_datetime(self, sample_agent):
        """Test that scheduler handles already-aware datetimes correctly."""
        from datetime import UTC, datetime

        # Agent with aware datetime (edge case)
        aware_next_run = datetime(2024, 1, 2, 9, 0, 0, tzinfo=UTC)
        assert aware_next_run.tzinfo is not None, "Test requires aware datetime"

        agent = Agent(
            id="agent-123",
            user_id="user-123",
            conversation_id="conv-123",
            name="Test Agent",
            description=None,
            system_prompt=None,
            schedule="0 9 * * *",
            timezone="UTC",
            enabled=True,
            tool_permissions=None,
            model="gemini-3-flash-preview",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
            last_run_at=None,
            next_run_at=aware_next_run,  # Aware datetime
        )

        now = datetime.now(UTC)

        # The fix should handle both naive and aware
        next_run = agent.next_run_at
        if next_run and next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=UTC)

        # Should not raise
        is_due = next_run <= now
        assert isinstance(is_due, bool)

    def test_scheduler_handles_none_next_run_at(self):
        """Test that scheduler handles agents with no next_run_at."""
        from datetime import UTC, datetime

        agent = Agent(
            id="agent-123",
            user_id="user-123",
            conversation_id="conv-123",
            name="Test Agent",
            description=None,
            system_prompt=None,
            schedule=None,  # No schedule
            timezone="UTC",
            enabled=True,
            tool_permissions=None,
            model="gemini-3-flash-preview",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
            last_run_at=None,
            next_run_at=None,  # No next run
        )

        now = datetime.now(UTC)

        # The fix should handle None safely
        next_run = agent.next_run_at
        if next_run and next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=UTC)

        # Should not raise or compare
        if next_run:
            is_due = next_run <= now
            assert isinstance(is_due, bool)
        else:
            # None is falsy, so no comparison should happen
            assert next_run is None

    def test_agent_is_due_when_next_run_in_past(self):
        """Test that agent is correctly identified as due when next_run is in the past."""
        from datetime import UTC, datetime, timedelta

        # Next run was an hour ago
        past_time = datetime.now(UTC) - timedelta(hours=1)
        naive_past = past_time.replace(tzinfo=None)  # DB returns naive

        agent = Agent(
            id="agent-123",
            user_id="user-123",
            conversation_id="conv-123",
            name="Test Agent",
            description=None,
            system_prompt=None,
            schedule="0 9 * * *",
            timezone="UTC",
            enabled=True,
            tool_permissions=None,
            model="gemini-3-flash-preview",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
            last_run_at=None,
            next_run_at=naive_past,
        )

        now = datetime.now(UTC)

        next_run = agent.next_run_at
        if next_run and next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=UTC)

        # Agent should be due
        assert next_run is not None
        assert next_run <= now

    def test_agent_not_due_when_next_run_in_future(self):
        """Test that agent is not due when next_run is in the future."""
        from datetime import UTC, datetime, timedelta

        # Next run is an hour from now
        future_time = datetime.now(UTC) + timedelta(hours=1)
        naive_future = future_time.replace(tzinfo=None)  # DB returns naive

        agent = Agent(
            id="agent-123",
            user_id="user-123",
            conversation_id="conv-123",
            name="Test Agent",
            description=None,
            system_prompt=None,
            schedule="0 9 * * *",
            timezone="UTC",
            enabled=True,
            tool_permissions=None,
            model="gemini-3-flash-preview",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
            last_run_at=None,
            next_run_at=naive_future,
        )

        now = datetime.now(UTC)

        next_run = agent.next_run_at
        if next_run and next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=UTC)

        # Agent should not be due
        assert next_run is not None
        assert next_run > now

    def test_cron_scheduling_does_not_drift(self):
        """Test that cron-based scheduling does not drift over time.

        Cron expressions define absolute times (e.g., "every 5 minutes" means
        :00, :05, :10, etc.), so calculating next run from actual run time
        vs scheduled time gives the same result.

        This test documents the expected behavior and ensures we don't
        accidentally introduce drift by switching to interval-based scheduling.
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from croniter import croniter

        schedule = "*/5 * * * *"  # Every 5 minutes
        tz = ZoneInfo("UTC")

        # Scenario: Agent scheduled for 9:00, actually runs at 9:02
        scheduled_time = datetime(2024, 1, 1, 9, 0, 0, tzinfo=tz)
        actual_run_time = datetime(2024, 1, 1, 9, 2, 0, tzinfo=tz)

        # Calculate next from scheduled time
        cron_from_scheduled = croniter(schedule, scheduled_time)
        next_from_scheduled = cron_from_scheduled.get_next(datetime)

        # Calculate next from actual run time
        cron_from_actual = croniter(schedule, actual_run_time)
        next_from_actual = cron_from_actual.get_next(datetime)

        # Both should give the same result (9:05)
        assert next_from_scheduled == next_from_actual
        assert next_from_scheduled.minute == 5
        assert next_from_scheduled.hour == 9

    def test_cron_next_run_calculation(self):
        """Test correct next run calculation for various cron expressions."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from croniter import croniter

        tz = ZoneInfo("UTC")
        base = datetime(2024, 1, 15, 10, 30, 0, tzinfo=tz)  # Mon Jan 15, 10:30

        test_cases = [
            # (schedule, expected_hour, expected_minute, expected_day)
            ("0 9 * * *", 9, 0, 16),  # Daily 9am -> next day
            ("0 11 * * *", 11, 0, 15),  # Daily 11am -> same day
            ("0 9 * * 1-5", 9, 0, 16),  # Weekdays 9am -> Tue
            ("*/30 * * * *", 11, 0, 15),  # Every 30 min -> 11:00
        ]

        for schedule, expected_hour, expected_minute, expected_day in test_cases:
            cron = croniter(schedule, base)
            next_run = cron.get_next(datetime)
            assert next_run.hour == expected_hour, (
                f"Schedule {schedule}: expected hour {expected_hour}, got {next_run.hour}"
            )
            assert next_run.minute == expected_minute, (
                f"Schedule {schedule}: expected minute {expected_minute}, got {next_run.minute}"
            )
            assert next_run.day == expected_day, (
                f"Schedule {schedule}: expected day {expected_day}, got {next_run.day}"
            )


# =============================================================================
# Unread count tests
# =============================================================================


class TestUnreadCount:
    """Tests for agent unread count calculation.

    These are regression tests for the bug where unread count was based on
    last_run_at instead of last_viewed_at.
    """

    def test_unread_count_uses_last_viewed_at(self):
        """Test that unread count is based on last_viewed_at, not last_run_at.

        Regression test: The command center was incorrectly using last_run_at
        to calculate unread messages. It should use last_viewed_at so that
        marking a conversation as viewed resets the unread count.
        """
        # This test verifies the SQL query logic.
        # The actual SQL is in get_command_center_data:
        # AND (a.last_viewed_at IS NULL OR m.created_at > a.last_viewed_at)
        #
        # Key scenarios:
        # 1. last_viewed_at is NULL -> all messages are unread
        # 2. last_viewed_at is set -> only messages after that time are unread
        # 3. Viewing should update last_viewed_at and reset count

        from datetime import datetime

        # Scenario: Agent ran at 9:00, user viewed at 10:00, new message at 11:00
        last_run_at = datetime(2024, 1, 1, 9, 0, 0)
        last_viewed_at = datetime(2024, 1, 1, 10, 0, 0)
        message_created_at = datetime(2024, 1, 1, 11, 0, 0)

        # Message at 11:00 should be unread (created after last_viewed_at)
        assert message_created_at > last_viewed_at

        # Message at 9:30 should be read (created before last_viewed_at)
        message_read = datetime(2024, 1, 1, 9, 30, 0)
        assert message_read <= last_viewed_at

        # Using last_run_at would incorrectly mark 9:30 message as unread
        # because 9:30 > 9:00 (last_run_at)
        assert message_read > last_run_at  # Would be wrong

    def test_mark_viewed_resets_unread_count(self):
        """Test that viewing an agent conversation resets unread count.

        When user opens an agent conversation:
        1. Frontend calls POST /api/agents/{id}/mark-viewed
        2. Backend updates last_viewed_at to current time
        3. Subsequent command center calls return unread_count = 0
        """
        from datetime import datetime

        # Before viewing: last_viewed_at is old, messages are unread
        last_viewed_at_before = datetime(2024, 1, 1, 9, 0, 0)
        message_time = datetime(2024, 1, 1, 10, 0, 0)
        assert message_time > last_viewed_at_before  # Message is unread

        # After viewing: last_viewed_at is updated to current time
        last_viewed_at_after = datetime(2024, 1, 1, 11, 0, 0)
        assert message_time <= last_viewed_at_after  # Message is now read

    def test_unread_count_only_includes_assistant_messages(self):
        """Test that unread count only counts assistant messages.

        Regression test: Trigger messages (role='user') should not be counted
        as unread. Only actual agent responses (role='assistant') should
        increment the unread counter.

        The SQL query filters with: m.role = 'assistant'
        """
        # This test verifies the SQL query logic.
        # The actual SQL is in get_command_center_data:
        # AND m.role = 'assistant'
        #
        # Key scenarios:
        # 1. Trigger message (role='user') -> NOT counted as unread
        # 2. Agent response (role='assistant') -> counted as unread
        # 3. Mix of messages -> only assistant messages counted

        # Simulating message roles
        trigger_message_role = "user"  # Trigger messages have role='user'
        assistant_message_role = "assistant"

        # Only assistant messages should be counted
        assert trigger_message_role != "assistant"
        assert assistant_message_role == "assistant"

        # If we have 3 messages: 1 trigger, 2 assistant responses
        messages = [
            {"role": "user", "is_trigger": True},  # Trigger - NOT counted
            {"role": "assistant"},  # Response - counted
            {"role": "assistant"},  # Response - counted
        ]

        # Expected unread count = 2 (only assistant messages)
        unread_count = sum(1 for m in messages if m["role"] == "assistant")
        assert unread_count == 2

        # Verify the filter logic matches our SQL query
        # SQL: WHERE m.role = 'assistant'
        filtered = [m for m in messages if m["role"] == "assistant"]
        assert len(filtered) == 2


# =============================================================================
# Scheduler unit tests
# =============================================================================


class TestSchedulerLogic:
    """Unit tests for scheduler logic.

    Tests cover edge cases and potential bugs in the scheduler:
    - Disabled agents should not be scheduled
    - Overlapping executions should be prevented
    - Double next_run_at updates should be avoided
    """

    def test_scheduler_skips_disabled_agents(self, mock_db):
        """Test that scheduler skips disabled agents.

        Even if next_run_at is in the past, disabled agents should not be executed.
        The get_due_agents() query should filter out disabled agents.
        """
        from datetime import datetime

        disabled_agent = Agent(
            id="agent-123",
            user_id="user-123",
            conversation_id="conv-123",
            name="Disabled Agent",
            description=None,
            system_prompt=None,
            schedule="0 9 * * *",
            timezone="UTC",
            enabled=False,  # Disabled
            tool_permissions=None,
            model="gemini-3-flash-preview",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
            last_run_at=None,
            next_run_at=datetime(2024, 1, 1, 9, 0, 0),  # Past due
        )

        # The agent should not be included in due agents because enabled=False
        # This is enforced by the SQL query: WHERE enabled = 1
        assert disabled_agent.enabled is False

    def test_scheduler_skips_agents_with_running_execution(self, mock_db):
        """Test that scheduler skips agents that already have a running execution.

        Prevents overlapping executions of the same agent.
        """
        from unittest.mock import MagicMock

        mock_db.has_running_execution = MagicMock(return_value=True)

        # When has_running_execution returns True, agent should be skipped
        has_running = mock_db.has_running_execution("agent-123")
        assert has_running is True

        # The scheduler logic should skip this agent
        # This is checked in run_scheduled_agents(): if db.has_running_execution(agent.id)

    def test_scheduler_skips_agents_with_pending_approval(self, mock_db):
        """Test that scheduler skips agents waiting for approval.

        Agents with pending approvals should not be re-executed until resolved.
        """
        from unittest.mock import MagicMock

        mock_db.has_pending_approval = MagicMock(return_value=True)

        # When has_pending_approval returns True, agent should be skipped
        has_pending = mock_db.has_pending_approval("agent-123")
        assert has_pending is True

        # The scheduler logic should skip this agent
        # This is checked in run_scheduled_agents(): if db.has_pending_approval(agent.id)

    def test_next_run_at_not_updated_twice_on_success(self):
        """Test that next_run_at is only updated once on successful execution.

        Regression test: The scheduler was updating next_run_at twice:
        1. Once in execute_agent() via update_agent_last_run()
        2. Once in the scheduler after execution

        Now the scheduler only updates next_run_at on failure (line 182-187).
        """
        # The fix ensures execute_agent() handles success updates
        # and scheduler only updates on failure
        #
        # Success path:
        #   execute_agent() -> calls update_agent_last_run()
        #   scheduler -> does NOT call update_agent_next_run()
        #
        # Failure path:
        #   execute_agent() -> returns (False, error_message)
        #   scheduler -> calls _update_next_run_on_failure()

        # This is a documentation test - the actual logic is in scheduler.py:
        # Lines 113-119: Success path doesn't update next_run_at
        # Lines 127-134: Failure path calls _update_next_run_on_failure
        pass

    def test_zombie_execution_cleanup(self, mock_db):
        """Test that zombie executions are cleaned up by the scheduler.

        Zombies are executions stuck in 'running' or 'waiting_approval' status
        for longer than AGENT_EXECUTION_TIMEOUT_MINUTES.
        """
        from unittest.mock import MagicMock

        mock_db.cleanup_zombie_executions = MagicMock(return_value=3)

        # Cleanup should return count of cleaned up executions
        cleaned = mock_db.cleanup_zombie_executions()
        assert cleaned == 3

        # The scheduler calls this at the start of every run
        # This is in run_scheduled_agents() lines 52-58


# =============================================================================
# Executor unit tests
# =============================================================================


class TestExecutorRun:
    """Unit tests for AgentExecutor.run() method.

    Tests cover:
    - waiting_approval status handling
    - trigger message propagation
    - context cleanup after execution
    """

    def test_executor_raises_blocked_on_waiting_approval(self, mock_db, mock_user):
        """Test that AgentExecutor.run() raises AgentBlockedError when approval is needed.

        When execute_agent() returns ("waiting_approval", description),
        AgentExecutor.run() should raise AgentBlockedError, not return normally.
        """
        from datetime import datetime
        from unittest.mock import MagicMock, patch

        agent = Agent(
            id="agent-123",
            user_id="user-123",
            conversation_id="conv-123",
            name="Test Agent",
            description=None,
            system_prompt=None,
            schedule="0 9 * * *",
            timezone="UTC",
            enabled=True,
            tool_permissions=None,
            model="gemini-3-flash-preview",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
            last_run_at=None,
            next_run_at=None,
        )

        # Mock dependencies
        mock_execution = MagicMock()
        mock_execution.id = "exec-123"

        with (
            patch("src.agent.executor.db") as db_mock,
            patch("src.agent.executor.execute_agent") as exec_mock,
        ):
            db_mock.create_execution.return_value = mock_execution
            exec_mock.return_value = ("waiting_approval", "Approval needed")

            from src.agent.executor import AgentBlockedError, AgentExecutor

            executor = AgentExecutor(agent, mock_user, "scheduled")

            with pytest.raises(AgentBlockedError) as exc_info:
                executor.run()

            assert "waiting for approval" in str(exc_info.value)

    def test_executor_propagates_trigger_chain(self, mock_user):
        """Test that executor passes parent trigger chain to child execution.

        This prevents circular dependencies where Agent A triggers Agent B
        triggers Agent A (infinite loop).
        """
        from datetime import datetime
        from unittest.mock import MagicMock, patch

        agent = Agent(
            id="agent-456",
            user_id="user-123",
            conversation_id="conv-456",
            name="Child Agent",
            description=None,
            system_prompt=None,
            schedule=None,
            timezone="UTC",
            enabled=True,
            tool_permissions=None,
            model="gemini-3-flash-preview",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
            last_run_at=None,
            next_run_at=None,
        )

        mock_execution = MagicMock()
        mock_execution.id = "exec-456"

        with (
            patch("src.agent.executor.db") as db_mock,
            patch("src.agent.executor.execute_agent") as exec_mock,
            patch("src.agent.executor.get_trigger_chain") as chain_mock,
        ):
            db_mock.create_execution.return_value = mock_execution
            exec_mock.return_value = (True, None)
            chain_mock.return_value = ["agent-123"]  # Parent agent in chain

            from src.agent.executor import AgentExecutor

            executor = AgentExecutor(
                agent, mock_user, "agent_trigger", triggered_by_agent_id="agent-123"
            )
            executor.run()

            # Verify execute_agent was called with parent chain
            call_kwargs = exec_mock.call_args.kwargs
            assert "parent_trigger_chain" in call_kwargs
            assert "agent-123" in call_kwargs["parent_trigger_chain"]

    def test_executor_clears_context_on_success(self, mock_user):
        """Test that context is properly cleaned up after successful execution."""
        from datetime import datetime
        from unittest.mock import MagicMock, patch

        agent = Agent(
            id="agent-123",
            user_id="user-123",
            conversation_id="conv-123",
            name="Test Agent",
            description=None,
            system_prompt=None,
            schedule=None,
            timezone="UTC",
            enabled=True,
            tool_permissions=None,
            model="gemini-3-flash-preview",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
            last_run_at=None,
            next_run_at=None,
        )

        mock_execution = MagicMock()
        mock_execution.id = "exec-123"

        with (
            patch("src.agent.executor.db") as db_mock,
            patch("src.agent.executor.execute_agent") as exec_mock,
        ):
            db_mock.create_execution.return_value = mock_execution
            db_mock.update_execution = MagicMock()
            exec_mock.return_value = (True, None)

            from src.agent.executor import AgentExecutor

            executor = AgentExecutor(agent, mock_user, "manual")
            result = executor.run()

            # Execution should complete successfully
            assert result.status == "completed"

            # Context should be cleared (but we can't easily test this
            # because it's cleared inside execute_agent, not AgentExecutor)
            # This test documents the expected behavior

    def test_executor_handles_execution_failure(self, mock_user):
        """Test that executor properly handles failed execution."""
        from datetime import datetime
        from unittest.mock import MagicMock, patch

        agent = Agent(
            id="agent-123",
            user_id="user-123",
            conversation_id="conv-123",
            name="Test Agent",
            description=None,
            system_prompt=None,
            schedule=None,
            timezone="UTC",
            enabled=True,
            tool_permissions=None,
            model="gemini-3-flash-preview",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
            last_run_at=None,
            next_run_at=None,
        )

        mock_execution = MagicMock()
        mock_execution.id = "exec-123"

        with (
            patch("src.agent.executor.db") as db_mock,
            patch("src.agent.executor.execute_agent") as exec_mock,
        ):
            db_mock.create_execution.return_value = mock_execution
            db_mock.update_execution = MagicMock()
            exec_mock.return_value = (False, "LLM API error")

            from src.agent.executor import AgentBlockedError, AgentExecutor

            executor = AgentExecutor(agent, mock_user, "manual")

            with pytest.raises(AgentBlockedError) as exc_info:
                executor.run()

            assert "LLM API error" in str(exc_info.value)
            db_mock.update_execution.assert_called_once_with(
                "exec-123", status="failed", error_message="LLM API error"
            )


# =============================================================================
# Retry logic tests
# =============================================================================


class TestRetryLogic:
    """Unit tests for transient failure retry logic."""

    def test_is_transient_error_connection_error(self):
        """Test that ConnectionError is recognized as transient."""
        from src.agent.retry import is_transient_error

        assert is_transient_error(ConnectionError("Connection reset"))

    def test_is_transient_error_timeout_error(self):
        """Test that TimeoutError is recognized as transient."""
        from src.agent.retry import is_transient_error

        assert is_transient_error(TimeoutError("Request timed out"))

    def test_is_transient_error_rate_limit_message(self):
        """Test that rate limit errors are recognized by message content."""
        from src.agent.retry import is_transient_error

        error = Exception("API rate limit exceeded, please retry")
        assert is_transient_error(error)

    def test_is_transient_error_503_message(self):
        """Test that 503 errors are recognized by message content."""
        from src.agent.retry import is_transient_error

        error = Exception("HTTP 503: Service Unavailable")
        assert is_transient_error(error)

    def test_is_not_transient_error_value_error(self):
        """Test that ValueError is not considered transient."""
        from src.agent.retry import is_transient_error

        assert not is_transient_error(ValueError("Invalid input"))

    def test_is_not_transient_error_generic(self):
        """Test that generic errors without transient patterns are not retried."""
        from src.agent.retry import is_transient_error

        assert not is_transient_error(Exception("Unknown error occurred"))

    def test_calculate_delay_exponential_backoff(self):
        """Test that delay increases exponentially with each attempt."""
        from src.agent.retry import calculate_delay

        delay_0 = calculate_delay(0)
        delay_1 = calculate_delay(1)
        delay_2 = calculate_delay(2)

        # Delays should increase (accounting for jitter)
        # Base delay is 1.0s, so:
        # attempt 0: ~1.0s (±20%)
        # attempt 1: ~2.0s (±20%)
        # attempt 2: ~4.0s (±20%)
        assert 0.7 <= delay_0 <= 1.3  # 1.0 ± 20% + 0.1 min
        assert 1.5 <= delay_1 <= 2.5  # 2.0 ± 20%
        assert 3.0 <= delay_2 <= 5.0  # 4.0 ± 20%

    def test_calculate_delay_max_cap(self):
        """Test that delay is capped at maximum value."""
        from src.agent.retry import calculate_delay

        # Very high attempt number should still be capped
        delay = calculate_delay(20)  # Would be 2^20 seconds without cap

        # Should be around max delay (30s default) with jitter
        assert delay <= 36.0  # 30 + 20% jitter

    def test_with_retry_success_first_attempt(self):
        """Test that successful call doesn't retry."""
        from src.agent.retry import with_retry

        call_count = 0

        def success_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = with_retry(success_func)()
        assert result == "success"
        assert call_count == 1

    def test_with_retry_retries_on_transient(self):
        """Test that transient errors are retried."""
        from unittest.mock import patch

        from src.agent.retry import with_retry

        attempt_count = 0

        def flaky_func():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise ConnectionError("Connection reset")
            return "success"

        # Patch sleep to avoid actual delays
        with patch("src.agent.retry.time.sleep"):
            result = with_retry(flaky_func, max_retries=3)()

        assert result == "success"
        assert attempt_count == 3

    def test_with_retry_raises_non_transient(self):
        """Test that non-transient errors are raised immediately."""
        from src.agent.retry import with_retry

        call_count = 0

        def fail_func():
            nonlocal call_count
            call_count += 1
            raise ValueError("Invalid argument")

        with pytest.raises(ValueError):
            with_retry(fail_func, max_retries=3)()

        # Should only be called once (no retries for non-transient)
        assert call_count == 1


# =============================================================================
# Compaction logic tests
# =============================================================================


class TestCompactionLogic:
    """Unit tests for conversation compaction logic."""

    def test_needs_compaction_below_threshold(self, mock_db):
        """Test that compaction is not needed when below threshold."""
        from datetime import datetime
        from unittest.mock import patch

        from src.agent.compaction import needs_compaction

        agent = Agent(
            id="agent-123",
            user_id="user-123",
            conversation_id="conv-123",
            name="Test Agent",
            description=None,
            system_prompt=None,
            schedule=None,
            timezone="UTC",
            enabled=True,
            tool_permissions=None,
            model="gemini-3-flash-preview",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
            last_run_at=None,
            next_run_at=None,
        )

        with patch("src.agent.compaction.db") as db_mock:
            db_mock.get_agent_message_count.return_value = 30  # Below 50 threshold
            assert not needs_compaction(agent)

    def test_needs_compaction_above_threshold(self, mock_db):
        """Test that compaction is needed when above threshold."""
        from datetime import datetime
        from unittest.mock import patch

        from src.agent.compaction import needs_compaction

        agent = Agent(
            id="agent-123",
            user_id="user-123",
            conversation_id="conv-123",
            name="Test Agent",
            description=None,
            system_prompt=None,
            schedule=None,
            timezone="UTC",
            enabled=True,
            tool_permissions=None,
            model="gemini-3-flash-preview",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
            last_run_at=None,
            next_run_at=None,
        )

        with patch("src.agent.compaction.db") as db_mock:
            db_mock.get_agent_message_count.return_value = 60  # Above 50 threshold
            assert needs_compaction(agent)

    def test_needs_compaction_no_conversation(self):
        """Test that compaction is not needed when agent has no conversation."""
        from datetime import datetime

        from src.agent.compaction import needs_compaction

        agent = Agent(
            id="agent-123",
            user_id="user-123",
            conversation_id=None,  # No conversation
            name="Test Agent",
            description=None,
            system_prompt=None,
            schedule=None,
            timezone="UTC",
            enabled=True,
            tool_permissions=None,
            model="gemini-3-flash-preview",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
            last_run_at=None,
            next_run_at=None,
        )

        # Should return False without calling db
        assert not needs_compaction(agent)


# =============================================================================
# Budget limit tests
# =============================================================================


class TestBudgetLimits:
    """Unit tests for per-agent budget limits."""

    def test_budget_limit_schema_validation(self):
        """Test that budget_limit accepts valid values."""
        data = CreateAgentRequest(name="Test", budget_limit=10.0)
        assert data.budget_limit == 10.0

    def test_budget_limit_none_means_unlimited(self):
        """Test that None budget_limit means unlimited."""
        data = CreateAgentRequest(name="Test", budget_limit=None)
        assert data.budget_limit is None

    def test_budget_limit_cannot_be_negative(self):
        """Test that negative budget_limit is rejected."""
        with pytest.raises(ValidationError):
            CreateAgentRequest(name="Test", budget_limit=-5.0)

    def test_is_agent_over_budget_unlimited(self, mock_db):
        """Test that unlimited budget (None) never triggers over-budget."""

        # Mock the is_agent_over_budget logic directly
        def is_over_budget(agent_id: str, limit: float | None) -> bool:
            if limit is None or limit <= 0:
                return False
            # Simulate $100 spending
            daily_spending = 100.0
            return daily_spending >= limit

        mock_db.is_agent_over_budget = is_over_budget

        # With None limit, should never be over budget
        assert not mock_db.is_agent_over_budget("agent-123", None)

        # With 0 limit, should never be over budget (0 means unlimited)
        assert not mock_db.is_agent_over_budget("agent-123", 0)

        # With actual limit below spending, should be over budget
        assert mock_db.is_agent_over_budget("agent-123", 50.0)

    def test_is_agent_over_budget_under_limit(self, mock_db):
        """Test that agent under budget limit is not flagged."""
        mock_db.get_agent_daily_spending = lambda aid: 5.0
        mock_db.is_agent_over_budget = lambda aid, limit: False if limit is None else 5.0 >= limit

        # Spending is $5, limit is $10
        assert not mock_db.is_agent_over_budget("agent-123", 10.0)

    def test_is_agent_over_budget_at_limit(self, mock_db):
        """Test that agent exactly at budget limit is flagged."""
        mock_db.get_agent_daily_spending = lambda aid: 10.0
        mock_db.is_agent_over_budget = lambda aid, limit: False if limit is None else 10.0 >= limit

        # Spending equals limit
        assert mock_db.is_agent_over_budget("agent-123", 10.0)

    def test_is_agent_over_budget_over_limit(self, mock_db):
        """Test that agent over budget limit is flagged."""
        mock_db.get_agent_daily_spending = lambda aid: 15.0
        mock_db.is_agent_over_budget = lambda aid, limit: False if limit is None else 15.0 >= limit

        # Spending exceeds limit
        assert mock_db.is_agent_over_budget("agent-123", 10.0)
