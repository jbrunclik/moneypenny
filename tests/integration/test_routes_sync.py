"""Integration tests for sync route.

Tests cover various race conditions and edge cases that can occur during
real-time synchronization between multiple clients/devices.
"""

import json
import time
from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Database, User


class TestSyncConversationsEndpoint:
    """Tests for GET /api/conversations/sync endpoint."""

    def test_full_sync_returns_all_conversations(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return all conversations with message counts on full sync."""
        conv1 = test_database.create_conversation(test_user.id, "Conv 1")
        conv2 = test_database.create_conversation(test_user.id, "Conv 2")
        test_database.add_message(conv1.id, "user", "Hello")
        test_database.add_message(conv1.id, "assistant", "Hi")

        response = client.get("/api/conversations/sync", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "conversations" in data
        assert "server_time" in data
        assert data["is_full_sync"] is True
        assert len(data["conversations"]) == 2

        # Check message counts
        conv1_data = next(c for c in data["conversations"] if c["id"] == conv1.id)
        conv2_data = next(c for c in data["conversations"] if c["id"] == conv2.id)
        assert conv1_data["message_count"] == 2
        assert conv2_data["message_count"] == 0

    def test_full_sync_with_explicit_param(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return all conversations when full=true even with since param."""
        conv = test_database.create_conversation(test_user.id, "Test")

        # Even with a future timestamp, full=true should return all conversations
        response = client.get(
            "/api/conversations/sync?since=2099-01-01T00:00:00&full=true",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["is_full_sync"] is True
        assert len(data["conversations"]) == 1
        assert data["conversations"][0]["id"] == conv.id

    def test_incremental_sync_returns_only_updated(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return only conversations updated after the given timestamp."""
        # Create first conversation (not used directly, just needs to exist before checkpoint)
        test_database.create_conversation(test_user.id, "Old Conv")

        # Wait and capture checkpoint
        time.sleep(0.01)
        checkpoint = datetime.now().isoformat()

        # Wait and create second conversation
        time.sleep(0.01)
        conv2 = test_database.create_conversation(test_user.id, "New Conv")
        test_database.add_message(conv2.id, "user", "Hello")

        response = client.get(
            f"/api/conversations/sync?since={checkpoint}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["is_full_sync"] is False
        assert len(data["conversations"]) == 1
        assert data["conversations"][0]["id"] == conv2.id
        assert data["conversations"][0]["message_count"] == 1

    def test_incremental_sync_empty_when_no_changes(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return empty list when no conversations updated since timestamp."""
        test_database.create_conversation(test_user.id, "Conv")

        # Wait and use future timestamp
        response = client.get(
            "/api/conversations/sync?since=2099-01-01T00:00:00",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["is_full_sync"] is False
        assert len(data["conversations"]) == 0

    def test_server_time_can_be_used_for_next_sync(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Server time from response should work as since param for next sync."""
        conv = test_database.create_conversation(test_user.id, "Conv")

        # First sync - get server time
        response1 = client.get("/api/conversations/sync", headers=auth_headers)
        data1 = json.loads(response1.data)
        server_time = data1["server_time"]
        assert len(data1["conversations"]) == 1

        # Wait and add message to update conversation
        time.sleep(0.01)
        test_database.add_message(conv.id, "user", "New message")

        # Second sync using server time from first response
        response2 = client.get(
            f"/api/conversations/sync?since={server_time}",
            headers=auth_headers,
        )
        data2 = json.loads(response2.data)

        # Should return the updated conversation
        assert len(data2["conversations"]) == 1
        assert data2["conversations"][0]["id"] == conv.id
        assert data2["conversations"][0]["message_count"] == 1

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/conversations/sync")
        assert response.status_code == 401

    def test_returns_empty_for_new_user(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return empty list for user with no conversations."""
        response = client.get("/api/conversations/sync", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["conversations"] == []
        assert data["is_full_sync"] is True


class TestSyncRaceConditions:
    """Tests for race conditions and edge cases in sync."""

    def test_message_added_during_sync_captured_in_next_sync(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Message added right at sync boundary should be captured in subsequent sync."""
        conv = test_database.create_conversation(test_user.id, "Conv")

        # First sync
        response1 = client.get("/api/conversations/sync", headers=auth_headers)
        data1 = json.loads(response1.data)
        server_time = data1["server_time"]
        assert data1["conversations"][0]["message_count"] == 0

        # Simulate message added exactly at/after the sync
        test_database.add_message(conv.id, "user", "Message at boundary")

        # Second sync should capture the new message
        response2 = client.get(
            f"/api/conversations/sync?since={server_time}",
            headers=auth_headers,
        )
        data2 = json.loads(response2.data)

        # Conversation should be in the result with updated message count
        assert len(data2["conversations"]) == 1
        assert data2["conversations"][0]["message_count"] == 1

    def test_conversation_deleted_between_syncs(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Deleted conversation should not appear in subsequent full sync."""
        conv1 = test_database.create_conversation(test_user.id, "Conv 1")
        conv2 = test_database.create_conversation(test_user.id, "Conv 2")

        # First sync - both conversations present
        response1 = client.get("/api/conversations/sync?full=true", headers=auth_headers)
        data1 = json.loads(response1.data)
        assert len(data1["conversations"]) == 2
        conv_ids_before = {c["id"] for c in data1["conversations"]}
        assert conv1.id in conv_ids_before
        assert conv2.id in conv_ids_before

        # Delete conv1
        test_database.delete_conversation(conv1.id, test_user.id)

        # Second full sync - only conv2 should be present
        response2 = client.get("/api/conversations/sync?full=true", headers=auth_headers)
        data2 = json.loads(response2.data)
        assert len(data2["conversations"]) == 1
        assert data2["conversations"][0]["id"] == conv2.id

    def test_rapid_successive_syncs(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Multiple rapid syncs should all return consistent data."""
        conv = test_database.create_conversation(test_user.id, "Conv")
        test_database.add_message(conv.id, "user", "Hello")

        # Perform 5 rapid syncs
        results = []
        for _ in range(5):
            response = client.get("/api/conversations/sync", headers=auth_headers)
            assert response.status_code == 200
            data = json.loads(response.data)
            results.append(data)

        # All should return consistent conversation data
        for result in results:
            assert len(result["conversations"]) == 1
            assert result["conversations"][0]["id"] == conv.id
            assert result["conversations"][0]["message_count"] == 1

    def test_conversation_title_changed_during_sync(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Title change should update conversation's updated_at and be captured in sync."""
        conv = test_database.create_conversation(test_user.id, "Original Title")

        # First sync
        response1 = client.get("/api/conversations/sync", headers=auth_headers)
        data1 = json.loads(response1.data)
        server_time = data1["server_time"]
        assert data1["conversations"][0]["title"] == "Original Title"

        # Wait and update title
        time.sleep(0.01)
        test_database.update_conversation(conv.id, test_user.id, title="New Title")

        # Second sync should capture the update
        response2 = client.get(
            f"/api/conversations/sync?since={server_time}",
            headers=auth_headers,
        )
        data2 = json.loads(response2.data)

        assert len(data2["conversations"]) == 1
        assert data2["conversations"][0]["title"] == "New Title"

    def test_multiple_conversations_updated_simultaneously(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Multiple conversations updated at nearly same time should all be captured."""
        conv1 = test_database.create_conversation(test_user.id, "Conv 1")
        conv2 = test_database.create_conversation(test_user.id, "Conv 2")
        conv3 = test_database.create_conversation(test_user.id, "Conv 3")

        # First sync
        response1 = client.get("/api/conversations/sync", headers=auth_headers)
        data1 = json.loads(response1.data)
        server_time = data1["server_time"]

        # Wait then update all three conversations rapidly
        time.sleep(0.01)
        test_database.add_message(conv1.id, "user", "Msg 1")
        test_database.add_message(conv2.id, "user", "Msg 2")
        test_database.add_message(conv3.id, "user", "Msg 3")

        # Second sync should capture all updates
        response2 = client.get(
            f"/api/conversations/sync?since={server_time}",
            headers=auth_headers,
        )
        data2 = json.loads(response2.data)

        assert len(data2["conversations"]) == 3
        updated_ids = {c["id"] for c in data2["conversations"]}
        assert conv1.id in updated_ids
        assert conv2.id in updated_ids
        assert conv3.id in updated_ids

    def test_sync_does_not_return_other_users_conversations(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Sync should never return conversations from other users."""
        # Create conversation for test user
        my_conv = test_database.create_conversation(test_user.id, "My Conv")
        test_database.add_message(my_conv.id, "user", "My message")

        # Create conversation for another user
        other_user = test_database.get_or_create_user("other@example.com", "Other User")
        other_conv = test_database.create_conversation(other_user.id, "Other Conv")
        test_database.add_message(other_conv.id, "user", "Other message")

        # Sync should only return test user's conversation
        response = client.get("/api/conversations/sync", headers=auth_headers)
        data = json.loads(response.data)

        assert len(data["conversations"]) == 1
        assert data["conversations"][0]["id"] == my_conv.id

    def test_large_message_count_accurate(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Message count should be accurate even with many messages."""
        conv = test_database.create_conversation(test_user.id, "Busy Chat")

        # Add 50 messages
        for i in range(50):
            role = "user" if i % 2 == 0 else "assistant"
            test_database.add_message(conv.id, role, f"Message {i}")

        response = client.get("/api/conversations/sync", headers=auth_headers)
        data = json.loads(response.data)

        assert data["conversations"][0]["message_count"] == 50


class TestSyncTimestampEdgeCases:
    """Tests for edge cases with timestamp handling in sync."""

    def test_sync_with_invalid_timestamp_format(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 400 for invalid timestamp format."""
        response = client.get(
            "/api/conversations/sync?since=invalid-date",
            headers=auth_headers,
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "timestamp" in data["error"]["message"].lower()
        assert data["error"]["details"]["field"] == "since"

    def test_sync_with_malformed_iso_timestamp(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 400 for malformed ISO timestamp."""
        # Missing time component
        response = client.get(
            "/api/conversations/sync?since=2024-01-01",
            headers=auth_headers,
        )
        # Python 3.11+ accepts date-only ISO format, so this may succeed
        # Test with clearly invalid format instead
        response = client.get(
            "/api/conversations/sync?since=not-a-date",
            headers=auth_headers,
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_sync_with_microsecond_precision_timestamp(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should handle timestamps with microsecond precision."""
        conv = test_database.create_conversation(test_user.id, "Conv")

        # Get timestamp with microseconds
        response1 = client.get("/api/conversations/sync", headers=auth_headers)
        data1 = json.loads(response1.data)
        server_time = data1["server_time"]
        # Verify server_time has proper format
        assert "T" in server_time
        # Should be parseable
        datetime.fromisoformat(server_time)

        time.sleep(0.01)
        test_database.add_message(conv.id, "user", "New")

        # Use the precise timestamp
        response2 = client.get(
            f"/api/conversations/sync?since={server_time}",
            headers=auth_headers,
        )
        data2 = json.loads(response2.data)
        assert len(data2["conversations"]) == 1

    def test_sync_with_various_iso_formats(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should handle various valid ISO timestamp formats."""
        test_database.create_conversation(test_user.id, "Conv")

        # Test with basic ISO format (no microseconds)
        response1 = client.get(
            "/api/conversations/sync?since=2000-01-01T00:00:00",
            headers=auth_headers,
        )
        assert response1.status_code == 200

        # Test with microseconds
        response2 = client.get(
            "/api/conversations/sync?since=2000-01-01T00:00:00.123456",
            headers=auth_headers,
        )
        assert response2.status_code == 200

    def test_sync_returns_conversations_ordered_by_updated_at(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return conversations ordered by updated_at DESC."""
        conv1 = test_database.create_conversation(test_user.id, "First")
        conv2 = test_database.create_conversation(test_user.id, "Second")

        # Update conv1 to make it most recent
        time.sleep(0.01)
        test_database.add_message(conv1.id, "user", "Update")

        response = client.get("/api/conversations/sync", headers=auth_headers)
        data = json.loads(response.data)

        assert len(data["conversations"]) == 2
        # conv1 should be first (most recently updated)
        assert data["conversations"][0]["id"] == conv1.id
        assert data["conversations"][1]["id"] == conv2.id


class TestSyncAgentConversationExclusion:
    """Tests for agent conversation exclusion from sync."""

    def test_sync_excludes_agent_conversations(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Sync should exclude agent conversations (is_agent=1)."""
        # Create a regular conversation
        regular_conv = test_database.create_conversation(test_user.id, "Regular Conv")
        test_database.add_message(regular_conv.id, "user", "Hello")

        # Create an agent and its conversation
        agent = test_database.create_agent(test_user.id, name="Test Agent")
        agent_conv = test_database.get_conversation(agent.conversation_id, test_user.id)

        # Add messages to agent conversation
        test_database.add_message(agent_conv.id, "user", "[Scheduled run]")
        test_database.add_message(agent_conv.id, "assistant", "Done")

        # Full sync should only return regular conversation
        response = client.get("/api/conversations/sync?full=true", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)

        # Should only have the regular conversation
        assert len(data["conversations"]) == 1
        assert data["conversations"][0]["id"] == regular_conv.id

        # Verify agent conversation is not included
        conv_ids = {c["id"] for c in data["conversations"]}
        assert agent.conversation_id not in conv_ids

    def test_incremental_sync_excludes_agent_conversations(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Incremental sync should also exclude agent conversations."""
        # Create regular conversation and get server time
        regular_conv = test_database.create_conversation(test_user.id, "Regular")

        response1 = client.get("/api/conversations/sync", headers=auth_headers)
        data1 = json.loads(response1.data)
        server_time = data1["server_time"]

        # Wait and create agent
        time.sleep(0.01)
        agent = test_database.create_agent(test_user.id, name="Test Agent")

        # Wait and update both conversations
        time.sleep(0.01)
        test_database.add_message(regular_conv.id, "user", "New message")
        test_database.add_message(agent.conversation_id, "user", "[Trigger]")

        # Incremental sync should only return regular conversation
        response2 = client.get(
            f"/api/conversations/sync?since={server_time}",
            headers=auth_headers,
        )

        data2 = json.loads(response2.data)

        # Should only have the regular conversation
        assert len(data2["conversations"]) == 1
        assert data2["conversations"][0]["id"] == regular_conv.id

    def test_sync_excludes_planning_conversations(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Sync should exclude planning conversations (is_planning=1)."""
        # Create regular conversation
        regular_conv = test_database.create_conversation(test_user.id, "Regular")

        # Create planning conversation using the proper method
        planning_conv = test_database.get_or_create_planner_conversation(test_user.id)
        test_database.add_message(planning_conv.id, "user", "Plan task")

        # Sync should only return regular conversation
        response = client.get("/api/conversations/sync", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)

        assert len(data["conversations"]) == 1
        assert data["conversations"][0]["id"] == regular_conv.id


class TestCursorSync:
    """GET /api/conversations/sync?cursor=N - the change-log sync (Oct 2026).

    Returns every chat conversation changed after the cursor WITH its state,
    so another device sees archive/trash/pin/delete - not just new messages.
    """

    def _cursor_sync(self, client: FlaskClient, headers: dict[str, str], cursor: int) -> dict:
        response = client.get(f"/api/conversations/sync?cursor={cursor}", headers=headers)
        assert response.status_code == 200
        return json.loads(response.data)

    def test_full_sync_returns_the_cursor_to_continue_from(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        test_database.create_conversation(test_user.id, "Existing")
        data = json.loads(
            client.get("/api/conversations/sync?full=true", headers=auth_headers).data
        )

        assert data["cursor"] == test_database.get_sync_cursor()
        assert self._cursor_sync(client, auth_headers, data["cursor"])["conversations"] == []

    def test_cursor_sync_returns_changed_conversations_with_their_state(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        archived = test_database.create_conversation(test_user.id, "Archived elsewhere")
        trashed = test_database.create_conversation(test_user.id, "Trashed elsewhere")
        pinned = test_database.create_conversation(test_user.id, "Pinned elsewhere")
        cursor = test_database.get_sync_cursor()

        test_database.archive_conversation(archived.id, test_user.id)
        test_database.trash_conversation(trashed.id, test_user.id)
        test_database.set_conversation_pinned(pinned.id, test_user.id, True)

        data = self._cursor_sync(client, auth_headers, cursor)
        by_id = {c["id"]: c for c in data["conversations"]}

        assert by_id[archived.id]["archived"] is True
        assert by_id[trashed.id]["trashed"] is True
        assert by_id[pinned.id]["pinned"] is True
        assert by_id[pinned.id]["archived"] is False
        assert data["cursor"] > cursor
        assert data["has_more"] is False
        assert data["is_full_sync"] is False

    def test_cursor_sync_reports_permanent_deletes(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Gone")
        cursor = test_database.get_sync_cursor()
        test_database.delete_conversation(conv.id, test_user.id)

        data = self._cursor_sync(client, auth_headers, cursor)

        assert data["removed_ids"] == [conv.id]
        assert data["conversations"] == []

    def test_cursor_sync_sees_a_deleted_message(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Chat")
        test_database.add_message(conv.id, "user", "q")
        last = test_database.add_message(conv.id, "assistant", "a")
        cursor = test_database.get_sync_cursor()
        test_database.delete_message(last.id, test_user.id)

        [change] = self._cursor_sync(client, auth_headers, cursor)["conversations"]

        assert change["message_count"] == 1
        assert change["last_message_id"] != last.id

    def test_cursor_sync_skips_non_chat_conversations(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        cursor = test_database.get_sync_cursor()
        planner = test_database.get_or_create_planner_conversation(test_user.id)
        test_database.add_message(planner.id, "user", "plan my day")

        data = self._cursor_sync(client, auth_headers, cursor)

        assert data["conversations"] == []
        assert data["cursor"] > cursor  # still consumed - nothing to re-send

    def test_cursor_sync_pages(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from src.config import Config

        monkeypatch.setattr(Config, "SYNC_CHANGES_PAGE_SIZE", 2)
        cursor = test_database.get_sync_cursor()
        for i in range(3):
            test_database.create_conversation(test_user.id, f"C{i}")

        first = self._cursor_sync(client, auth_headers, cursor)
        second = self._cursor_sync(client, auth_headers, first["cursor"])

        assert len(first["conversations"]) == 2 and first["has_more"] is True
        assert len(second["conversations"]) == 1 and second["has_more"] is False

    def test_invalid_cursor_is_rejected(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/api/conversations/sync?cursor=abc", headers=auth_headers)
        assert response.status_code == 400
