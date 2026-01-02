"""Integration tests for pagination routes."""

import json
import time
from typing import TYPE_CHECKING

from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, User


class TestConversationsPagination:
    """Tests for GET /api/conversations pagination."""

    def test_first_page_without_cursor(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return first page when no cursor provided."""
        # Create multiple conversations
        for i in range(5):
            test_database.create_conversation(test_user.id, title=f"Conv {i}")
            time.sleep(0.01)  # Ensure different timestamps

        response = client.get("/api/conversations?limit=3", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "conversations" in data
        assert "pagination" in data
        assert len(data["conversations"]) == 3
        assert data["pagination"]["has_more"] is True
        assert data["pagination"]["total_count"] == 5
        assert data["pagination"]["next_cursor"] is not None

    def test_next_page_with_cursor(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return next page when cursor is provided."""
        # Create conversations
        for i in range(5):
            test_database.create_conversation(test_user.id, title=f"Conv {i}")
            time.sleep(0.01)

        # Get first page
        response1 = client.get("/api/conversations?limit=2", headers=auth_headers)
        data1 = json.loads(response1.data)
        cursor = data1["pagination"]["next_cursor"]

        # Get second page using cursor
        response2 = client.get(f"/api/conversations?limit=2&cursor={cursor}", headers=auth_headers)
        data2 = json.loads(response2.data)

        assert response2.status_code == 200
        assert len(data2["conversations"]) == 2
        assert data2["pagination"]["has_more"] is True

        # Ensure no duplicates between pages
        page1_ids = {c["id"] for c in data1["conversations"]}
        page2_ids = {c["id"] for c in data2["conversations"]}
        assert len(page1_ids & page2_ids) == 0, "Pages should not have duplicate conversations"

    def test_last_page_has_more_false(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should set has_more to false on last page."""
        # Create 3 conversations
        for i in range(3):
            test_database.create_conversation(test_user.id, title=f"Conv {i}")
            time.sleep(0.01)

        # Get first page with larger limit
        response = client.get("/api/conversations?limit=10", headers=auth_headers)
        data = json.loads(response.data)

        assert response.status_code == 200
        assert len(data["conversations"]) == 3
        assert data["pagination"]["has_more"] is False
        assert data["pagination"]["next_cursor"] is None

    def test_cursor_handles_same_timestamp(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should handle tie-breaking when conversations have same timestamp."""
        # Create conversations with controlled timestamps (simulated same time)
        # The cursor format is {timestamp}:{id}, so even with same timestamp,
        # the id provides tie-breaking
        convs = []
        for i in range(4):
            conv = test_database.create_conversation(test_user.id, title=f"Conv {i}")
            convs.append(conv)
            # Note: SQLite datetime has second precision, but cursor uses full timestamp
            # Adding tiny sleep to ensure different microseconds in case DB supports them
            time.sleep(0.001)

        # Get all conversations in pages of 2
        all_conv_ids = []
        cursor = None
        for _ in range(3):  # Should take 2 iterations + 1 empty
            url = "/api/conversations?limit=2"
            if cursor:
                url += f"&cursor={cursor}"
            response = client.get(url, headers=auth_headers)
            data = json.loads(response.data)

            for c in data["conversations"]:
                all_conv_ids.append(c["id"])

            if not data["pagination"]["has_more"]:
                break
            cursor = data["pagination"]["next_cursor"]

        # Should have gotten all 4 conversations without duplicates
        assert len(all_conv_ids) == 4
        assert len(set(all_conv_ids)) == 4, "No duplicate conversations"

    def test_total_count_accuracy(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should return accurate total_count across all pages."""
        # Create 7 conversations
        for i in range(7):
            test_database.create_conversation(test_user.id, title=f"Conv {i}")

        # Check total on first page
        response1 = client.get("/api/conversations?limit=3", headers=auth_headers)
        data1 = json.loads(response1.data)
        assert data1["pagination"]["total_count"] == 7

        # Check total on subsequent page (should be same)
        cursor = data1["pagination"]["next_cursor"]
        response2 = client.get(f"/api/conversations?limit=3&cursor={cursor}", headers=auth_headers)
        data2 = json.loads(response2.data)
        assert data2["pagination"]["total_count"] == 7

    def test_limit_clamped_to_max(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should clamp limit to max page size."""
        # Create conversations
        for i in range(5):
            test_database.create_conversation(test_user.id, title=f"Conv {i}")

        # Request with excessive limit
        response = client.get("/api/conversations?limit=9999", headers=auth_headers)
        data = json.loads(response.data)

        assert response.status_code == 200
        # Should return all 5 (clamped to max, which is 100)
        assert len(data["conversations"]) == 5

    def test_invalid_limit_uses_default(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should use default limit when invalid value provided."""
        for i in range(5):
            test_database.create_conversation(test_user.id, title=f"Conv {i}")

        # Request with invalid limit
        response = client.get("/api/conversations?limit=abc", headers=auth_headers)
        assert response.status_code == 200

    def test_message_count_included(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        """Should include message_count in paginated results."""
        # Create conversation with messages
        conv = test_database.create_conversation(test_user.id, title="Conv with msgs")
        test_database.add_message(conv.id, "user", "Hello")
        test_database.add_message(conv.id, "assistant", "Hi there")

        response = client.get("/api/conversations?limit=10", headers=auth_headers)
        data = json.loads(response.data)

        assert response.status_code == 200
        conv_data = next(c for c in data["conversations"] if c["id"] == conv.id)
        assert "message_count" in conv_data
        assert conv_data["message_count"] == 2

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/conversations")
        assert response.status_code == 401


class TestMessagesPagination:
    """Tests for GET /api/conversations/<id>/messages pagination."""

    def test_first_page_returns_newest(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Should return newest messages on first page."""
        # Add messages
        for i in range(5):
            test_database.add_message(test_conversation.id, "user", f"Message {i}")
            time.sleep(0.01)

        response = client.get(
            f"/api/conversations/{test_conversation.id}/messages?limit=3",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data["messages"]) == 3
        assert data["pagination"]["has_older"] is True
        assert data["pagination"]["has_newer"] is False  # At newest
        assert data["pagination"]["total_count"] == 5

        # Verify order: should be chronological (oldest first in page)
        # But the page contains the NEWEST 3 messages
        contents = [m["content"] for m in data["messages"]]
        # Messages 2, 3, 4 should be returned (newest 3), in chronological order
        assert contents == ["Message 2", "Message 3", "Message 4"]

    def test_older_direction_loads_older_messages(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Should load older messages when using older cursor."""
        # Add messages
        for i in range(6):
            test_database.add_message(test_conversation.id, "user", f"Message {i}")
            time.sleep(0.01)

        # Get first page (newest)
        response1 = client.get(
            f"/api/conversations/{test_conversation.id}/messages?limit=3",
            headers=auth_headers,
        )
        data1 = json.loads(response1.data)
        older_cursor = data1["pagination"]["older_cursor"]

        # Get older messages
        response2 = client.get(
            f"/api/conversations/{test_conversation.id}/messages?limit=3&cursor={older_cursor}&direction=older",
            headers=auth_headers,
        )
        data2 = json.loads(response2.data)

        assert response2.status_code == 200
        assert len(data2["messages"]) == 3
        assert data2["pagination"]["has_older"] is False  # At oldest
        assert data2["pagination"]["has_newer"] is True

        # Should be messages 0, 1, 2 (older ones)
        contents = [m["content"] for m in data2["messages"]]
        assert contents == ["Message 0", "Message 1", "Message 2"]

    def test_newer_direction_loads_newer_messages(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Should load newer messages when using newer cursor and direction."""
        # Add messages
        for i in range(6):
            test_database.add_message(test_conversation.id, "user", f"Message {i}")
            time.sleep(0.01)

        # Get first page (newest)
        response1 = client.get(
            f"/api/conversations/{test_conversation.id}/messages?limit=3",
            headers=auth_headers,
        )
        data1 = json.loads(response1.data)

        # Navigate to older
        older_cursor = data1["pagination"]["older_cursor"]
        response2 = client.get(
            f"/api/conversations/{test_conversation.id}/messages?limit=3&cursor={older_cursor}&direction=older",
            headers=auth_headers,
        )
        data2 = json.loads(response2.data)

        # Navigate back to newer
        newer_cursor = data2["pagination"]["newer_cursor"]
        response3 = client.get(
            f"/api/conversations/{test_conversation.id}/messages?limit=3&cursor={newer_cursor}&direction=newer",
            headers=auth_headers,
        )
        data3 = json.loads(response3.data)

        assert response3.status_code == 200
        contents = [m["content"] for m in data3["messages"]]
        # Should get back to messages 3, 4, 5
        assert contents == ["Message 3", "Message 4", "Message 5"]

    def test_no_skip_or_duplicate_during_pagination(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Should not skip or duplicate items during full pagination."""
        # Add messages
        for i in range(10):
            test_database.add_message(test_conversation.id, "user", f"Message {i}")
            time.sleep(0.005)

        # Paginate through all messages
        all_contents = []
        cursor = None
        seen_ids = set()

        # Start from newest and go older
        for _ in range(10):  # Safety limit
            url = f"/api/conversations/{test_conversation.id}/messages?limit=3"
            if cursor:
                url += f"&cursor={cursor}&direction=older"

            response = client.get(url, headers=auth_headers)
            data = json.loads(response.data)

            for m in data["messages"]:
                assert m["id"] not in seen_ids, f"Duplicate message: {m['id']}"
                seen_ids.add(m["id"])
                all_contents.append(m["content"])

            if not data["pagination"]["has_older"]:
                break
            cursor = data["pagination"]["older_cursor"]

        # Should have all 10 messages
        assert len(all_contents) == 10
        # Note: Since we go from newest to oldest, and each page is chronological,
        # we get: [7,8,9], [4,5,6], [1,2,3], [0] or similar groupings
        # But all messages should be present
        for i in range(10):
            assert f"Message {i}" in all_contents

    def test_404_for_nonexistent_conversation(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 404 for non-existent conversation."""
        response = client.get(
            "/api/conversations/nonexistent-id/messages",
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_404_for_other_users_conversation(
        self,
        client: FlaskClient,
        test_database: Database,
    ) -> None:
        """Should return 404 when accessing another user's conversation messages."""
        # Create another user and their conversation
        other_user = test_database.get_or_create_user(email="other@example.com", name="Other")
        other_conv = test_database.create_conversation(other_user.id)
        test_database.add_message(other_conv.id, "user", "Hello")

        # Try to access with original test user's auth
        from src.auth.jwt_auth import create_token

        test_user = test_database.get_or_create_user(email="test@example.com", name="Test")
        token = create_token(test_user)

        response = client.get(
            f"/api/conversations/{other_conv.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 404

    def test_empty_conversation_returns_empty_list(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return empty list for conversation with no messages."""
        response = client.get(
            f"/api/conversations/{test_conversation.id}/messages",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["messages"] == []
        assert data["pagination"]["total_count"] == 0
        assert data["pagination"]["has_older"] is False
        assert data["pagination"]["has_newer"] is False

    def test_invalid_direction_defaults_to_older(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Should default to 'older' for invalid direction."""
        test_database.add_message(test_conversation.id, "user", "Hello")

        response = client.get(
            f"/api/conversations/{test_conversation.id}/messages?direction=invalid",
            headers=auth_headers,
        )

        assert response.status_code == 200

    def test_requires_auth(
        self,
        client: FlaskClient,
        test_conversation: Conversation,
    ) -> None:
        """Should return 401 without authentication."""
        response = client.get(f"/api/conversations/{test_conversation.id}/messages")
        assert response.status_code == 401


class TestConversationDetailPagination:
    """Tests for GET /api/conversations/<id> message pagination."""

    def test_default_returns_newest_messages(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Should return newest messages by default."""
        # Add messages
        for i in range(5):
            test_database.add_message(test_conversation.id, "user", f"Message {i}")
            time.sleep(0.01)

        response = client.get(
            f"/api/conversations/{test_conversation.id}?message_limit=3",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "message_pagination" in data
        assert len(data["messages"]) == 3
        assert data["message_pagination"]["total_count"] == 5

        # Should be newest messages
        contents = [m["content"] for m in data["messages"]]
        assert contents == ["Message 2", "Message 3", "Message 4"]

    def test_includes_conversation_metadata(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should include full conversation metadata alongside paginated messages."""
        response = client.get(
            f"/api/conversations/{test_conversation.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)

        # Check conversation fields are present
        assert data["id"] == test_conversation.id
        assert data["title"] == test_conversation.title
        assert data["model"] == test_conversation.model
        assert "created_at" in data
        assert "updated_at" in data
        assert "messages" in data
        assert "message_pagination" in data

    def test_message_cursor_navigation(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Should support cursor navigation via conversation endpoint."""
        # Add messages
        for i in range(6):
            test_database.add_message(test_conversation.id, "user", f"Message {i}")
            time.sleep(0.01)

        # Get first page
        response1 = client.get(
            f"/api/conversations/{test_conversation.id}?message_limit=3",
            headers=auth_headers,
        )
        data1 = json.loads(response1.data)
        older_cursor = data1["message_pagination"]["older_cursor"]

        # Get older messages
        response2 = client.get(
            f"/api/conversations/{test_conversation.id}?message_limit=3&message_cursor={older_cursor}&direction=older",
            headers=auth_headers,
        )
        data2 = json.loads(response2.data)

        assert response2.status_code == 200
        contents = [m["content"] for m in data2["messages"]]
        assert contents == ["Message 0", "Message 1", "Message 2"]
