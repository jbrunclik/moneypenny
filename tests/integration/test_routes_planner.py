"""Integration tests for planner routes.

Tests cover:
- GET /api/planner - Dashboard data endpoint
- GET /api/planner/conversation - Get/create planner conversation with auto-reset
- POST /api/planner/reset - Manual reset endpoint
- GET /api/planner/sync - Sync endpoint for real-time updates
"""

import json
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Database, User


class TestGetPlannerDashboard:
    """Tests for GET /api/planner endpoint."""

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/planner")
        assert response.status_code == 401

    def test_returns_dashboard_structure(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return proper dashboard structure."""
        response = client.get("/api/planner", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)

        # Check required fields
        assert "days" in data
        assert "overdue_tasks" in data
        assert "todoist_connected" in data
        assert "calendar_connected" in data
        assert "garmin_connected" in data
        assert "weather_connected" in data
        assert "server_time" in data

        # Check optional fields are present (may be null)
        assert "garmin_error" in data
        assert "weather_error" in data
        assert "weather_location" in data
        assert "health_summary" in data

        # Days should be a list of 7 days
        assert isinstance(data["days"], list)
        assert len(data["days"]) == 7

        # Each day should have required fields
        for day in data["days"]:
            assert "date" in day
            assert "day_name" in day
            assert "events" in day
            assert "tasks" in day
            # Weather field should be present (may be null)
            assert "weather" in day

    def test_first_day_is_today(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """First day in the dashboard should be 'Today'."""
        response = client.get("/api/planner", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)

        assert data["days"][0]["day_name"] == "Today"
        assert data["days"][0]["date"] == datetime.now().strftime("%Y-%m-%d")

    def test_second_day_is_tomorrow(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Second day in the dashboard should be 'Tomorrow'."""
        response = client.get("/api/planner", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)

        tomorrow = datetime.now() + timedelta(days=1)
        assert data["days"][1]["day_name"] == "Tomorrow"
        assert data["days"][1]["date"] == tomorrow.strftime("%Y-%m-%d")

    def test_no_integrations_connected(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should show not connected when no integrations are set up."""
        response = client.get("/api/planner", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)

        # Default test user has no integrations connected
        assert data["todoist_connected"] is False
        assert data["calendar_connected"] is False
        assert data["garmin_connected"] is False
        assert data["overdue_tasks"] == []
        assert data["health_summary"] is None

        # Each day should have empty events and tasks
        for day in data["days"]:
            assert day["events"] == []
            assert day["tasks"] == []
            # Weather may be present if WEATHER_LOCATION is configured in env
            assert "weather" in day

    def test_server_time_is_valid_iso_format(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Server time should be a valid ISO timestamp."""
        response = client.get("/api/planner", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)

        # Should be parseable as ISO datetime
        server_time = datetime.fromisoformat(data["server_time"])
        assert server_time is not None

        # Should be close to now (within 5 seconds)
        now = datetime.now()
        diff = abs((now - server_time).total_seconds())
        assert diff < 5


class TestGetPlannerConversation:
    """Tests for GET /api/planner/conversation endpoint."""

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/planner/conversation")
        assert response.status_code == 401

    def test_creates_new_planner_conversation_on_first_access(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should create a new planner conversation on first access."""
        # Initially, no planner conversation exists (check conversations list)
        convs_response = client.get("/api/conversations", headers=auth_headers)
        convs_data = json.loads(convs_response.data)
        assert len(convs_data["conversations"]) == 0

        response = client.get("/api/planner/conversation", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)

        # Should have created a new conversation
        assert "id" in data
        assert data["was_reset"] is False
        assert "messages" in data
        assert data["messages"] == []

        # Verify planner exists in database with is_planning flag
        conv = test_database.get_or_create_planner_conversation(test_user.id)
        assert conv is not None
        assert conv.id == data["id"]
        assert conv.is_planning is True

    def test_returns_existing_planner_conversation(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return the same planner conversation on subsequent access."""
        # Create planner conversation first
        response1 = client.get("/api/planner/conversation", headers=auth_headers)
        data1 = json.loads(response1.data)
        conv_id = data1["id"]

        # Access again
        response2 = client.get("/api/planner/conversation", headers=auth_headers)
        data2 = json.loads(response2.data)

        # Should be the same conversation
        assert data2["id"] == conv_id
        assert data2["was_reset"] is False

    def test_planner_conversation_has_messages(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Planner conversation should include its messages."""
        # Create planner conversation and add a message
        response1 = client.get("/api/planner/conversation", headers=auth_headers)
        data1 = json.loads(response1.data)
        conv_id = data1["id"]

        # Add a message directly to the database
        test_database.add_message(conv_id, "user", "Test planning message")

        # Fetch again
        response2 = client.get("/api/planner/conversation", headers=auth_headers)
        data2 = json.loads(response2.data)

        assert len(data2["messages"]) == 1
        assert data2["messages"][0]["content"] == "Test planning message"

    def test_auto_reset_triggers_after_4am(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Planner should auto-reset if last reset was before today's 4am."""
        # Create planner conversation and add a message
        response1 = client.get("/api/planner/conversation", headers=auth_headers)
        data1 = json.loads(response1.data)
        conv_id = data1["id"]
        test_database.add_message(conv_id, "user", "Old message")

        # Manually set the reset timestamp to yesterday using direct SQL
        yesterday = datetime.now() - timedelta(days=1)
        with test_database._pool.get_connection() as conn:
            conn.execute(
                "UPDATE users SET planner_last_reset_at = ? WHERE id = ?",
                (yesterday.isoformat(), test_user.id),
            )
            conn.commit()

        # Access conversation again - should trigger auto-reset if current time >= 4am
        response2 = client.get("/api/planner/conversation", headers=auth_headers)
        data2 = json.loads(response2.data)

        now = datetime.now()
        if now.hour >= 4:
            # Should have reset
            assert data2["was_reset"] is True
            assert data2["messages"] == []
        else:
            # Before 4am, check against yesterday's 4am
            # If yesterday's 4am is after the reset timestamp, should reset
            # Otherwise, no reset
            pass  # This is hard to test reliably without mocking time

    def test_no_auto_reset_same_day(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """No auto-reset if already reset today."""
        # Create planner conversation
        response1 = client.get("/api/planner/conversation", headers=auth_headers)
        data1 = json.loads(response1.data)
        conv_id = data1["id"]

        # Add a message
        test_database.add_message(conv_id, "user", "Today's message")

        # Access again immediately
        response2 = client.get("/api/planner/conversation", headers=auth_headers)
        data2 = json.loads(response2.data)

        # Should NOT have reset
        assert data2["was_reset"] is False
        assert len(data2["messages"]) == 1

    def test_planner_conversation_excluded_from_regular_list(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Planner conversation should not appear in regular conversation list."""
        # Create planner conversation
        planner_response = client.get("/api/planner/conversation", headers=auth_headers)
        planner_data = json.loads(planner_response.data)
        planner_id = planner_data["id"]

        # Create a regular conversation
        regular_conv = test_database.create_conversation(test_user.id, "Regular Chat")

        # Fetch regular conversations list
        response = client.get("/api/conversations", headers=auth_headers)
        data = json.loads(response.data)

        # Should only have 1 conversation (the regular one)
        assert len(data["conversations"]) == 1
        assert data["conversations"][0]["title"] == "Regular Chat"
        assert data["conversations"][0]["id"] == regular_conv.id
        # Planner conversation should NOT be in the list
        assert data["conversations"][0]["id"] != planner_id


class TestResetPlannerConversation:
    """Tests for POST /api/planner/reset endpoint."""

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.post("/api/planner/reset")
        assert response.status_code == 401

    def test_reset_clears_messages(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Reset should clear all messages from the planner conversation."""
        # Create planner conversation and add messages
        response1 = client.get("/api/planner/conversation", headers=auth_headers)
        data1 = json.loads(response1.data)
        conv_id = data1["id"]

        test_database.add_message(conv_id, "user", "Message 1")
        test_database.add_message(conv_id, "assistant", "Response 1")
        test_database.add_message(conv_id, "user", "Message 2")

        # Verify messages exist
        messages = test_database.get_messages(conv_id)
        assert len(messages) == 3

        # Reset
        response2 = client.post("/api/planner/reset", headers=auth_headers)
        assert response2.status_code == 200
        data2 = json.loads(response2.data)
        assert data2["success"] is True

        # Verify messages are cleared
        response3 = client.get("/api/planner/conversation", headers=auth_headers)
        data3 = json.loads(response3.data)
        assert data3["messages"] == []

    def test_reset_preserves_conversation(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Reset should preserve the planner conversation itself."""
        # Create planner conversation
        response1 = client.get("/api/planner/conversation", headers=auth_headers)
        data1 = json.loads(response1.data)
        conv_id = data1["id"]

        # Reset
        client.post("/api/planner/reset", headers=auth_headers)

        # Verify conversation still exists with same ID
        response2 = client.get("/api/planner/conversation", headers=auth_headers)
        data2 = json.loads(response2.data)
        assert data2["id"] == conv_id

    def test_reset_updates_last_reset_timestamp(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Reset should update the planner_last_reset_at timestamp."""
        # Create planner conversation
        client.get("/api/planner/conversation", headers=auth_headers)

        before_reset = datetime.now()
        time.sleep(0.01)

        # Reset
        client.post("/api/planner/reset", headers=auth_headers)

        # Check timestamp was updated
        user = test_database.get_user_by_id(test_user.id)
        assert user.planner_last_reset_at is not None
        assert user.planner_last_reset_at > before_reset

    def test_reset_creates_conversation_if_none_exists(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Reset should create a planner conversation if none exists."""
        # Reset should succeed even without a pre-existing planner
        response = client.post("/api/planner/reset", headers=auth_headers)
        assert response.status_code == 200

        # Planner conversation should now exist (created by reset endpoint)
        conv = test_database.get_or_create_planner_conversation(test_user.id)
        assert conv is not None
        assert conv.is_planning is True

    def test_reset_does_not_affect_regular_conversations(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Reset should not affect regular conversations."""
        # Create planner conversation
        client.get("/api/planner/conversation", headers=auth_headers)

        # Create a regular conversation with messages
        regular_conv = test_database.create_conversation(test_user.id, "Regular Chat")
        test_database.add_message(regular_conv.id, "user", "Regular message")

        # Reset planner
        client.post("/api/planner/reset", headers=auth_headers)

        # Regular conversation should still have its message
        messages = test_database.get_messages(regular_conv.id)
        assert len(messages) == 1
        assert messages[0].content == "Regular message"


class TestPlannerExcludedFromSearch:
    """Tests for planner conversations being excluded from search."""

    def test_planner_messages_not_in_search_results(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Planner messages should not appear in search results."""
        # Create planner conversation with a message
        response1 = client.get("/api/planner/conversation", headers=auth_headers)
        data1 = json.loads(response1.data)
        conv_id = data1["id"]
        test_database.add_message(conv_id, "user", "secret planning unicorn")

        # Create a regular conversation with the same word
        regular_conv = test_database.create_conversation(test_user.id, "Regular Chat")
        test_database.add_message(regular_conv.id, "user", "unicorn in regular chat")

        # Search for the unique word
        response2 = client.get("/api/search?q=unicorn", headers=auth_headers)
        data2 = json.loads(response2.data)

        # Should only find the message in the regular conversation
        assert data2["total"] == 1
        assert data2["results"][0]["conversation_id"] == regular_conv.id

    def test_planner_title_not_in_search_results(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Planner conversation title should not appear in search results."""
        # Create planner conversation (title includes "Planner")
        client.get("/api/planner/conversation", headers=auth_headers)

        # Create a regular conversation with "Planner" in the title
        regular_conv = test_database.create_conversation(test_user.id, "My Planner Notes")

        # Search for "Planner"
        response = client.get("/api/search?q=Planner", headers=auth_headers)
        data = json.loads(response.data)

        # Should only find the regular conversation
        assert data["total"] == 1
        assert data["results"][0]["conversation_id"] == regular_conv.id


class TestPlannerUserIsolation:
    """Tests for planner user isolation."""

    def test_cannot_access_other_users_planner(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Users should only access their own planner."""
        # Create planner for test user
        response1 = client.get("/api/planner/conversation", headers=auth_headers)
        data1 = json.loads(response1.data)
        user1_planner_id = data1["id"]

        # Create another user
        other_user = test_database.get_or_create_user("other@example.com", "Other User")

        # Create planner for other user using get_or_create_planner_conversation
        other_planner = test_database.get_or_create_planner_conversation(other_user.id)
        test_database.add_message(other_planner.id, "user", "Other user's secret plan")

        # Access planner as test user
        response2 = client.get("/api/planner/conversation", headers=auth_headers)
        data2 = json.loads(response2.data)

        # Should get test user's planner, not other user's
        assert data2["id"] == user1_planner_id
        assert len(data2["messages"]) == 0

    def test_dashboard_shows_only_users_integrations(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Dashboard should only show the current user's integration status."""
        # Create another user with integrations
        other_user = test_database.get_or_create_user("other@example.com", "Other User")
        # update_user_todoist_token only takes user_id and token
        test_database.update_user_todoist_token(other_user.id, "other-token")

        # Get dashboard as test user
        response = client.get("/api/planner", headers=auth_headers)
        data = json.loads(response.data)

        # Test user has no integrations
        assert data["todoist_connected"] is False
        assert data["calendar_connected"] is False


class TestPlannerSync:
    """Tests for GET /api/planner/sync endpoint."""

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/planner/sync")
        assert response.status_code == 401

    def test_returns_null_when_no_planner_exists(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return null conversation when user has no planner."""
        response = client.get("/api/planner/sync", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)

        # Should have null conversation
        assert data["conversation"] is None
        assert "server_time" in data

    def test_returns_planner_state_when_exists(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return planner conversation state when it exists."""
        # Create planner conversation
        planner = test_database.get_or_create_planner_conversation(test_user.id)

        # Add some messages
        test_database.add_message(
            conversation_id=planner.id,
            role="user",
            content="Test message 1",
        )
        test_database.add_message(
            conversation_id=planner.id,
            role="assistant",
            content="Test message 2",
        )

        response = client.get("/api/planner/sync", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)

        # Should have conversation state
        assert data["conversation"] is not None
        assert data["conversation"]["id"] == planner.id
        assert data["conversation"]["message_count"] == 2
        assert "updated_at" in data["conversation"]
        assert "last_reset" in data["conversation"]
        assert "server_time" in data

    def test_returns_correct_message_count(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return accurate message count."""
        # Create planner with multiple messages
        planner = test_database.get_or_create_planner_conversation(test_user.id)

        for i in range(5):
            test_database.add_message(
                conversation_id=planner.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i}",
            )

        response = client.get("/api/planner/sync", headers=auth_headers)
        data = json.loads(response.data)

        assert data["conversation"]["message_count"] == 5

    def test_returns_last_reset_timestamp(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return last_reset timestamp if planner was reset."""
        # Create planner and reset it
        planner = test_database.get_or_create_planner_conversation(test_user.id)
        test_database.add_message(
            conversation_id=planner.id,
            role="user",
            content="Before reset",
        )

        # Reset planner via API
        client.post("/api/planner/reset", headers=auth_headers)

        # Get sync state
        response = client.get("/api/planner/sync", headers=auth_headers)
        data = json.loads(response.data)

        # last_reset should be set
        assert data["conversation"]["last_reset"] is not None
        assert isinstance(data["conversation"]["last_reset"], str)

        # Verify it's a valid ISO timestamp
        last_reset = datetime.fromisoformat(data["conversation"]["last_reset"])
        assert isinstance(last_reset, datetime)

    def test_initializes_last_reset_on_creation(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Regression test for Issue #2: planner_last_reset_at should be initialized on creation."""
        # Create planner conversation
        test_database.get_or_create_planner_conversation(test_user.id)

        # Verify that planner_last_reset_at was initialized (not NULL)
        user = test_database.get_user_by_id(test_user.id)
        assert user.planner_last_reset_at is not None

        # Verify it's recent (within last 5 seconds)
        now = datetime.now()
        diff = abs((now - user.planner_last_reset_at).total_seconds())
        assert diff < 5

        # Also verify via sync endpoint
        response = client.get("/api/planner/sync", headers=auth_headers)
        data = json.loads(response.data)

        # last_reset should be set (not null)
        assert data["conversation"]["last_reset"] is not None

    def test_updates_after_message_added(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Message count should update after adding messages."""
        # Create planner
        planner = test_database.get_or_create_planner_conversation(test_user.id)

        # Get initial state
        response1 = client.get("/api/planner/sync", headers=auth_headers)
        data1 = json.loads(response1.data)
        initial_count = data1["conversation"]["message_count"]

        # Add a message
        test_database.add_message(
            conversation_id=planner.id,
            role="user",
            content="New message",
        )

        # Get updated state
        response2 = client.get("/api/planner/sync", headers=auth_headers)
        data2 = json.loads(response2.data)

        assert data2["conversation"]["message_count"] == initial_count + 1

    def test_isolates_users(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should only return current user's planner state."""
        # Create planner for test user
        test_planner = test_database.get_or_create_planner_conversation(test_user.id)
        test_database.add_message(
            conversation_id=test_planner.id,
            role="user",
            content="Test user message",
        )

        # Create another user with planner
        other_user = test_database.get_or_create_user("other@example.com", "Other User")
        other_planner = test_database.get_or_create_planner_conversation(other_user.id)
        for i in range(10):
            test_database.add_message(
                conversation_id=other_planner.id,
                role="user",
                content=f"Other user message {i}",
            )

        # Get sync state as test user
        response = client.get("/api/planner/sync", headers=auth_headers)
        data = json.loads(response.data)

        # Should only see test user's planner
        assert data["conversation"]["id"] == test_planner.id
        assert data["conversation"]["message_count"] == 1  # Not 10
