"""Integration tests for around_message_id parameter in messages endpoint."""

import json
import time
from typing import TYPE_CHECKING

from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, User


class TestMessagesAroundEndpoint:
    """Tests for GET /api/conversations/<id>/messages with around_message_id."""

    def test_around_message_id_returns_centered_page(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        """Should return messages centered around the target message."""
        # Create 20 messages
        messages = []
        for i in range(20):
            msg = test_database.add_message(
                conversation_id=test_conversation.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i}",
            )
            messages.append(msg)
            time.sleep(0.01)

        # Get messages around message 10
        target_msg = messages[10]
        response = client.get(
            f"/api/conversations/{test_conversation.id}/messages"
            f"?around_message_id={target_msg.id}&limit=10",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)

        # Should have ~10 messages centered around target
        assert len(data["messages"]) == 10

        # Target message should be in the results
        result_ids = [m["id"] for m in data["messages"]]
        assert target_msg.id in result_ids

        # Should have both older and newer cursors/flags
        assert data["pagination"]["has_older"] is True
        assert data["pagination"]["has_newer"] is True
        assert data["pagination"]["older_cursor"] is not None
        assert data["pagination"]["newer_cursor"] is not None

    def test_around_message_id_not_found(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return 404 when around_message_id doesn't exist."""
        response = client.get(
            f"/api/conversations/{test_conversation.id}/messages"
            "?around_message_id=nonexistent-message-id",
            headers=auth_headers,
        )

        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["error"]["code"] == "NOT_FOUND"
        assert "Message" in data["error"]["message"]

    def test_around_message_id_from_different_conversation(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        """Should return 404 when message belongs to a different conversation."""
        # Create a message in the test conversation
        msg = test_database.add_message(
            conversation_id=test_conversation.id,
            role="user",
            content="Test message",
        )

        # Create another conversation
        other_conv = test_database.create_conversation(test_user.id, title="Other Conv")

        # Try to get messages from other_conv using message from test_conversation
        response = client.get(
            f"/api/conversations/{other_conv.id}/messages?around_message_id={msg.id}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_around_message_id_ignores_cursor_and_direction(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        """Should ignore cursor and direction when around_message_id is provided."""
        # Create messages
        messages = []
        for i in range(10):
            msg = test_database.add_message(
                conversation_id=test_conversation.id,
                role="user",
                content=f"Message {i}",
            )
            messages.append(msg)
            time.sleep(0.01)

        target_msg = messages[5]

        # Request with around_message_id AND cursor/direction (which should be ignored)
        response = client.get(
            f"/api/conversations/{test_conversation.id}/messages"
            f"?around_message_id={target_msg.id}"
            f"&cursor=some-cursor&direction=newer&limit=6",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)

        # Should still center around target, not use cursor/direction
        result_ids = [m["id"] for m in data["messages"]]
        assert target_msg.id in result_ids

    def test_around_message_at_beginning(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        """Should handle target at the beginning of conversation."""
        # Create messages
        messages = []
        for i in range(10):
            msg = test_database.add_message(
                conversation_id=test_conversation.id,
                role="user",
                content=f"Message {i}",
            )
            messages.append(msg)
            time.sleep(0.01)

        # Target is the first message
        target_msg = messages[0]
        response = client.get(
            f"/api/conversations/{test_conversation.id}/messages"
            f"?around_message_id={target_msg.id}&limit=10",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)

        # No older messages
        assert data["pagination"]["has_older"] is False
        assert data["pagination"]["older_cursor"] is None

        # Has newer messages
        assert data["pagination"]["has_newer"] is True

    def test_around_message_at_end(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        """Should handle target at the end of conversation."""
        # Create messages
        messages = []
        for i in range(10):
            msg = test_database.add_message(
                conversation_id=test_conversation.id,
                role="user",
                content=f"Message {i}",
            )
            messages.append(msg)
            time.sleep(0.01)

        # Target is the last message
        target_msg = messages[9]
        response = client.get(
            f"/api/conversations/{test_conversation.id}/messages"
            f"?around_message_id={target_msg.id}&limit=10",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)

        # Has older messages
        assert data["pagination"]["has_older"] is True

        # No newer messages
        assert data["pagination"]["has_newer"] is False
        assert data["pagination"]["newer_cursor"] is None

    def test_around_message_pagination_continues(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        """Should return cursors that work for continued pagination."""
        # Create messages
        messages = []
        for i in range(30):
            msg = test_database.add_message(
                conversation_id=test_conversation.id,
                role="user",
                content=f"Message {i}",
            )
            messages.append(msg)
            time.sleep(0.01)

        # Get messages around message 15
        target_msg = messages[15]
        response = client.get(
            f"/api/conversations/{test_conversation.id}/messages"
            f"?around_message_id={target_msg.id}&limit=10",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        older_cursor = data["pagination"]["older_cursor"]
        newer_cursor = data["pagination"]["newer_cursor"]

        # Use older_cursor to get more older messages
        response_older = client.get(
            f"/api/conversations/{test_conversation.id}/messages"
            f"?cursor={older_cursor}&direction=older&limit=5",
            headers=auth_headers,
        )
        assert response_older.status_code == 200
        data_older = json.loads(response_older.data)
        assert len(data_older["messages"]) == 5

        # Use newer_cursor to get more newer messages
        response_newer = client.get(
            f"/api/conversations/{test_conversation.id}/messages"
            f"?cursor={newer_cursor}&direction=newer&limit=5",
            headers=auth_headers,
        )
        assert response_newer.status_code == 200
        data_newer = json.loads(response_newer.data)
        assert len(data_newer["messages"]) == 5

        # Verify no overlap between around results and older/newer results
        around_ids = {m["id"] for m in data["messages"]}
        older_ids = {m["id"] for m in data_older["messages"]}
        newer_ids = {m["id"] for m in data_newer["messages"]}

        assert len(around_ids & older_ids) == 0, "Around and older should not overlap"
        assert len(around_ids & newer_ids) == 0, "Around and newer should not overlap"

    def test_around_message_response_format(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        """Should return standard MessagesListResponse format."""
        msg = test_database.add_message(
            conversation_id=test_conversation.id,
            role="user",
            content="Test message",
        )

        response = client.get(
            f"/api/conversations/{test_conversation.id}/messages?around_message_id={msg.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)

        # Verify structure matches standard response
        assert "messages" in data
        assert "pagination" in data
        assert isinstance(data["messages"], list)

        # Pagination has all expected fields
        pagination = data["pagination"]
        assert "older_cursor" in pagination
        assert "newer_cursor" in pagination
        assert "has_older" in pagination
        assert "has_newer" in pagination
        assert "total_count" in pagination

    def test_conversation_not_found(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 404 when conversation doesn't exist."""
        response = client.get(
            "/api/conversations/nonexistent-conv-id/messages?around_message_id=some-message-id",
            headers=auth_headers,
        )

        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["error"]["code"] == "NOT_FOUND"
        assert "Conversation" in data["error"]["message"]

    def test_around_message_with_small_conversation(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        """Should handle conversation with fewer messages than limit."""
        # Create just 3 messages
        messages = []
        for i in range(3):
            msg = test_database.add_message(
                conversation_id=test_conversation.id,
                role="user",
                content=f"Message {i}",
            )
            messages.append(msg)
            time.sleep(0.01)

        # Request with limit=100 (much larger than message count)
        target_msg = messages[1]
        response = client.get(
            f"/api/conversations/{test_conversation.id}/messages"
            f"?around_message_id={target_msg.id}&limit=100",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)

        # Should return all 3 messages
        assert len(data["messages"]) == 3

        # No pagination in either direction
        assert data["pagination"]["has_older"] is False
        assert data["pagination"]["has_newer"] is False
