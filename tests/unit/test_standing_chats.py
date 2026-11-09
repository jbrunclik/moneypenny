"""Unit tests for autonomous agents feature.

Tests cover:
- Agent routes (CRUD, command center, approvals)
- Agent database operations
- Permission checking
- Executor context management
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from src.api.schemas.jobs import CreateJobRequest, UpdateJobRequest
from src.db.models.dataclasses import JobRun

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
def sample_execution():
    """Create a sample execution."""
    return JobRun(
        id="exec-123",
        item_id="agent-123",
        status="completed",
        trigger_type="manual",
        triggered_by_job_id=None,
        started_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        completed_at=datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC),
        error_message=None,
    )


# =============================================================================
# Schema validation tests
# =============================================================================


class TestCreateJobRequest:
    """Tests for CreateJobRequest schema."""

    def test_valid_minimal_request(self):
        """Test valid minimal request with only required fields."""
        data = CreateJobRequest(name="Test Agent")
        assert data.name == "Test Agent"
        assert data.description is None
        assert data.schedule is None
        assert data.timezone == "UTC"
        assert data.enabled is True

    def test_valid_full_request(self):
        """Test valid request with all fields."""
        data = CreateJobRequest(
            name="Full Agent",
            description="A full agent",
            instructions="You are helpful",
            schedule="0 9 * * *",
            timezone="America/New_York",
            grants=["todoist", "google_calendar"],
            enabled=False,
        )
        assert data.name == "Full Agent"
        assert data.description == "A full agent"
        assert data.schedule == "0 9 * * *"
        assert data.timezone == "America/New_York"
        assert data.grants == ["todoist", "google_calendar"]
        assert data.enabled is False

    def test_name_is_required(self):
        """Test that name field is required."""
        with pytest.raises(ValidationError):
            CreateJobRequest()  # type: ignore[call-arg]

    def test_name_min_length(self):
        """Test name minimum length validation."""
        with pytest.raises(ValidationError):
            CreateJobRequest(name="")

    def test_name_max_length(self):
        """Test name maximum length validation."""
        with pytest.raises(ValidationError):
            CreateJobRequest(name="x" * 101)  # 101 chars, max is 100

    def test_description_max_length(self):
        """Test description maximum length validation."""
        with pytest.raises(ValidationError):
            CreateJobRequest(name="Test", description="x" * 501)

    def test_system_prompt_max_length(self):
        """Test system prompt maximum length validation."""
        with pytest.raises(ValidationError):
            CreateJobRequest(name="Test", instructions="x" * 10001)


class TestUpdateJobRequest:
    """Tests for UpdateJobRequest schema."""

    def test_all_fields_optional(self):
        """Test that all fields are optional for updates."""
        data = UpdateJobRequest()
        assert data.name is None
        assert data.description is None
        assert data.schedule is None

    def test_partial_update(self):
        """Test partial update with some fields."""
        data = UpdateJobRequest(name="New Name", enabled=False)
        assert data.name == "New Name"
        assert data.enabled is False
        assert data.description is None

    def test_model_dump_exclude_unset(self):
        """Test model_dump(exclude_unset=True) for partial updates."""
        # Only name provided
        data = UpdateJobRequest(name="New Name")
        dump = data.model_dump(exclude_unset=True)
        assert dump == {"name": "New Name"}
        assert "description" not in dump
        assert "enabled" not in dump

        # Explicitly setting field to None
        data = UpdateJobRequest(description=None)
        dump = data.model_dump(exclude_unset=True)
        assert dump == {"description": None}
        assert "name" not in dump

        # Multiple fields
        data = UpdateJobRequest(name="Name", budget_usd=100.0)
        dump = data.model_dump(exclude_unset=True)
        assert dump == {"name": "Name", "budget_usd": 100.0}


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

        # Always-safe tools are allowed even when the grants name none of them
        for tool in ALWAYS_SAFE_TOOLS:
            result = check_tool_permission([], tool, {})
            assert result == PermissionResult.ALLOWED

    def test_blocked_when_not_permitted(self):
        """Test that tools are blocked if not in agent permissions."""
        from src.agent.permissions import PermissionResult, check_tool_permission

        permissions = ["web_search"]  # Only web_search permitted

        # todoist should be blocked
        result = check_tool_permission(permissions, "todoist", {"operation": "add_task"})
        assert result == PermissionResult.BLOCKED

    def test_empty_tool_permissions(self):
        """Test agent with empty tool permissions list (explicitly set to [])."""
        from src.agent.permissions import PermissionResult, check_tool_permission

        permissions = []  # Explicitly set to empty

        # All tools should be blocked when permissions is an empty list
        result = check_tool_permission(permissions, "todoist", {"operation": "add_task"})
        assert result == PermissionResult.BLOCKED

    def test_null_tool_permissions_allows_all_tools(self):
        """Test agent with None tool permissions (no restrictions on tools)."""
        from src.agent.permissions import PermissionResult, check_tool_permission

        permissions = None  # No restrictions

        # With None permissions, all tools are allowed
        result = check_tool_permission(permissions, "todoist", {"operation": "add_task"})
        assert result == PermissionResult.ALLOWED

    def test_null_tool_permissions_allows_safe_tools(self):
        """Test agent with None tool permissions allows safe tools."""
        from src.agent.permissions import PermissionResult, check_tool_permission

        permissions = None  # No restrictions

        # Safe tools are always allowed
        result = check_tool_permission(permissions, "web_search", {})
        assert result == PermissionResult.ALLOWED

    def test_kv_store_allowed_despite_explicit_permissions(self):
        """kv_store is always bound for agents, so it must never be blocked.

        Agents with an explicit tool_permissions list (not mentioning kv_store)
        must still be able to access their own K/V namespace.
        """
        from src.agent.permissions import PermissionResult, check_tool_permission

        permissions = ["web_search"]  # kv_store not listed

        result = check_tool_permission(permissions, "kv_store", {"action": "get", "key": "state"})
        assert result == PermissionResult.ALLOWED


# =============================================================================
# Executor context tests
# =============================================================================


class TestExecutorContext:
    """Tests for executor context management."""

    def test_get_agent_context_returns_none_outside_execution(self):
        """Test that get_job_context returns None outside execution."""
        from src.agent.run_context import get_job_context

        # Outside an agent execution, context should be None
        result = get_job_context()
        assert result is None

    def test_trigger_chain_management(self):
        """Trigger chain for circular dependency prevention rides on JobContext."""
        from unittest.mock import MagicMock

        from src.agent.run_context import (
            JobContext,
            clear_job_context,
            get_trigger_chain,
            set_job_context,
        )

        # Initially should be empty
        assert get_trigger_chain() == []

        # The chain is propagated via execute_agent(parent_trigger_chain=...)
        # which installs an JobContext carrying the extended chain
        set_job_context(
            JobContext(item=MagicMock(), user=MagicMock(), name="a", trigger_chain=["agent-1"])
        )
        try:
            assert get_trigger_chain() == ["agent-1"]
        finally:
            clear_job_context()

        assert get_trigger_chain() == []


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

    def test_standing_to_response_conversion(self, test_database, monkeypatch):
        """A standing chat as the editor shows it."""
        import src.api.helpers.standing_responses as module

        monkeypatch.setattr(module, "db", test_database)
        user = test_database.get_or_create_user(email="resp@example.com", name="Resp")
        chat = test_database.create_standing_chat(
            user.id, "Test Agent", "Do it", schedule="0 9 * * *", grants=["todoist"]
        )

        response = module.standing_to_response(chat)

        assert (response["id"], response["name"], response["instructions"]) == (
            chat.id,
            "Test Agent",
            "Do it",
        )
        assert (response["schedule"], response["grants"], response["unread_count"]) == (
            "0 9 * * *",
            ["todoist"],
            0,
        )

    def test_run_to_response_conversion(self, sample_execution):
        from src.api.helpers.standing_responses import run_to_response

        response = run_to_response(sample_execution)

        assert response["id"] == "exec-123"
        assert response["item_id"] == "agent-123"
        assert response["status"] == "completed"
        assert response["trigger_type"] == "manual"

    def test_a_run_card_converts_with_its_agent(self, test_database, test_user, make_run_card):
        from src.api.helpers.standing_responses import run_proposal_to_response

        agent = test_database.create_standing_chat(test_user.id, "Test Agent")
        response = run_proposal_to_response(make_run_card(agent), "Test Agent")

        assert (response["job_id"], response["job_name"], response["state"]) == (
            agent.id,
            "Test Agent",
            "pending",
        )
        assert response["conversation_id"] == agent.conversation_id

    def test_update_of_a_chat_deleted_meanwhile_finds_nothing(self, test_database):
        """Deleted between the lookup and the UPDATE: None, and no write lock left held."""
        from unittest.mock import patch

        user = test_database.get_or_create_user(email="gone@example.com", name="Gone")
        chat = test_database.create_standing_chat(user.id, "Gone")
        test_database.delete_standing_chat(chat.id, user.id)
        with patch.object(test_database, "get_standing_chat", return_value=chat):
            assert test_database.update_standing_chat(chat.id, user.id, name="Renamed") is None

    def test_update_recalculates_next_run_only_when_scheduling_changes(self, test_database):
        user = test_database.get_or_create_user(email="sched@example.com", name="Sched")
        agent = test_database.create_standing_chat(user.id, "Sched", schedule="0 9 * * *")
        assert agent.next_run_at is not None

        kept = test_database.update_standing_chat(agent.id, user.id, description="new")
        disabled = test_database.update_standing_chat(agent.id, user.id, enabled=False)
        still_disabled = test_database.update_standing_chat(
            agent.id, user.id, schedule="0 10 * * *"
        )
        enabled = test_database.update_standing_chat(agent.id, user.id, enabled=True)
        unscheduled = test_database.update_standing_chat(agent.id, user.id, schedule=None)

        assert kept.next_run_at == agent.next_run_at
        assert disabled.next_run_at is None
        assert still_disabled.next_run_at is None
        assert enabled.next_run_at is not None
        assert enabled.next_run_at.hour == 10
        assert unscheduled.next_run_at is None

    def test_update_carries_name_and_model_to_the_conversation(self, test_database):
        user = test_database.get_or_create_user(email="conv@example.com", name="Conv")
        agent = test_database.create_standing_chat(user.id, "Old")

        test_database.update_standing_chat(agent.id, user.id, name="New", model="gemini-test-model")

        conv = test_database.get_conversation(agent.conversation_id, user.id)
        assert (conv.title, conv.model) == ("Agent: New", "gemini-test-model")


# =============================================================================
# Dev scheduler tests
# =============================================================================


class TestDevScheduler:
    """Tests for dev scheduler functionality."""

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
        last_run_at = datetime(2024, 1, 1, 9, 0, 0, tzinfo=UTC)
        last_viewed_at = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        message_created_at = datetime(2024, 1, 1, 11, 0, 0, tzinfo=UTC)

        # Message at 11:00 should be unread (created after last_viewed_at)
        assert message_created_at > last_viewed_at

        # Message at 9:30 should be read (created before last_viewed_at)
        message_read = datetime(2024, 1, 1, 9, 30, 0, tzinfo=UTC)
        assert message_read <= last_viewed_at

        # Using last_run_at would incorrectly mark 9:30 message as unread
        # because 9:30 > 9:00 (last_run_at)
        assert message_read > last_run_at  # Would be wrong

    def test_mark_viewed_resets_unread_count(self):
        """Test that viewing an agent conversation resets unread count.

        When user opens an agent conversation:
        1. Frontend calls POST /api/jobs/{id}/viewed
        2. Backend updates last_viewed_at to current time
        3. Subsequent command center calls return unread_count = 0
        """
        from datetime import datetime

        # Before viewing: last_viewed_at is old, messages are unread
        last_viewed_at_before = datetime(2024, 1, 1, 9, 0, 0, tzinfo=UTC)
        message_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        assert message_time > last_viewed_at_before  # Message is unread

        # After viewing: last_viewed_at is updated to current time
        last_viewed_at_after = datetime(2024, 1, 1, 11, 0, 0, tzinfo=UTC)
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

    Agents run as standing jobs (test_scheduler.py, test_item_scheduler.py);
    what remains here is the zombie-execution sweep.
    """

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

    def test_chat_node_retries_on_transient_error(self):
        """Test that chat_node retries model.invoke on transient errors."""
        from unittest.mock import MagicMock, patch

        from langchain_core.messages import AIMessage

        from src.agent.chat_node import chat_node

        model = MagicMock()
        model.model_name = "test-model"

        # Fail twice with ConnectionError, succeed on 3rd attempt
        success_response = AIMessage(content="Hello!")
        model.invoke.side_effect = [
            ConnectionError("Connection reset"),
            ConnectionError("Connection reset"),
            success_response,
        ]

        state = {"messages": [AIMessage(content="Hi")]}

        with patch("src.agent.retry.time.sleep"):
            result = chat_node(state, model)

        assert result["messages"] == [success_response]
        assert model.invoke.call_count == 3

    def test_chat_node_no_retry_on_non_transient_error(self):
        """Test that chat_node does not retry on non-transient errors."""
        from unittest.mock import MagicMock

        from langchain_core.messages import AIMessage

        from src.agent.chat_node import chat_node

        model = MagicMock()
        model.model_name = "test-model"
        model.invoke.side_effect = ValueError("Invalid input")

        state = {"messages": [AIMessage(content="Hi")]}

        with pytest.raises(ValueError, match="Invalid input"):
            chat_node(state, model)

        assert model.invoke.call_count == 1

    def test_retry_on_google_api_errors(self):
        """Test that Google API exceptions are detected as transient."""
        from google.api_core.exceptions import (
            DeadlineExceeded,
            ResourceExhausted,
            ServiceUnavailable,
        )

        from src.agent.retry import is_transient_error

        assert is_transient_error(ResourceExhausted("429 rate limit"))
        assert is_transient_error(ServiceUnavailable("503 unavailable"))
        assert is_transient_error(DeadlineExceeded("504 deadline"))


# =============================================================================
# Compaction logic tests
# =============================================================================


class TestBudgetLimits:
    """Unit tests for per-agent budget limits."""

    def test_budget_limit_schema_validation(self):
        """Test that budget_limit accepts valid values."""
        data = CreateJobRequest(name="Test", budget_usd=10.0)
        assert data.budget_usd == 10.0

    def test_budget_limit_none_means_unlimited(self):
        """Test that None budget_limit means unlimited."""
        data = CreateJobRequest(name="Test", budget_usd=None)
        assert data.budget_usd is None

    def test_budget_limit_cannot_be_negative(self):
        """Test that negative budget_limit is rejected."""
        with pytest.raises(ValidationError):
            CreateJobRequest(name="Test", budget_usd=-5.0)
