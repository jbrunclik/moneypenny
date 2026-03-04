"""Integration tests for conversation routes."""

import json
from typing import TYPE_CHECKING

from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Conversation, Database


class TestListConversations:
    """Tests for GET /api/conversations endpoint."""

    def test_lists_user_conversations(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return list of user's conversations."""
        response = client.get("/api/conversations", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "conversations" in data
        assert len(data["conversations"]) >= 1
        assert any(c["id"] == test_conversation.id for c in data["conversations"])

    def test_includes_message_count(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Should include message_count for sync initialization.

        This test ensures the list endpoint returns message counts so the
        frontend can properly initialize local counts and avoid false
        'unread' badges on initial load.
        """
        # Add some messages to the conversation
        test_database.add_message(test_conversation.id, "user", "Message 1")
        test_database.add_message(test_conversation.id, "assistant", "Response 1")
        test_database.add_message(test_conversation.id, "user", "Message 2")

        response = client.get("/api/conversations", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)

        # Find the test conversation in the response
        conv = next(c for c in data["conversations"] if c["id"] == test_conversation.id)

        # Verify message_count is present and accurate
        assert "message_count" in conv, "message_count must be present for sync initialization"
        assert conv["message_count"] == 3, "message_count should reflect actual message count"

    def test_returns_empty_list_for_new_user(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return empty list when user has no conversations."""
        # Note: test_user is created but has no conversations initially
        # (test_conversation fixture not used here)
        response = client.get("/api/conversations", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["conversations"] == []

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/conversations")
        assert response.status_code == 401


class TestCreateConversation:
    """Tests for POST /api/conversations endpoint."""

    def test_creates_conversation(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should create new conversation."""
        response = client.post(
            "/api/conversations",
            headers=auth_headers,
            json={"model": "gemini-3-flash-preview"},
        )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert "id" in data
        assert data["model"] == "gemini-3-flash-preview"
        assert "title" in data

    def test_creates_with_default_model(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should use default model when not specified."""
        from src.config import Config

        response = client.post(
            "/api/conversations",
            headers=auth_headers,
            json={},
        )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["model"] == Config.DEFAULT_MODEL

    def test_creates_with_default_title(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should create conversation with default title (API doesn't accept title)."""
        response = client.post(
            "/api/conversations",
            headers=auth_headers,
            json={},
        )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["title"] == "New Conversation"  # Default title

    def test_rejects_invalid_model(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should return 400 for invalid model."""
        response = client.post(
            "/api/conversations",
            headers=auth_headers,
            json={"model": "invalid-model-xyz"},
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data

    def test_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.post("/api/conversations", json={})
        assert response.status_code == 401


class TestGetConversation:
    """Tests for GET /api/conversations/<conv_id> endpoint."""

    def test_gets_conversation_with_messages(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Should return conversation with its messages."""
        # Add a message
        test_database.add_message(test_conversation.id, "user", "Hello")

        response = client.get(
            f"/api/conversations/{test_conversation.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["id"] == test_conversation.id
        assert data["title"] == test_conversation.title
        assert "messages" in data
        assert len(data["messages"]) == 1
        assert data["messages"][0]["content"] == "Hello"

    def test_returns_404_for_nonexistent(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 for non-existent conversation."""
        response = client.get(
            "/api/conversations/nonexistent-id",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_returns_404_for_other_users_conversation(
        self,
        client: FlaskClient,
        test_database: Database,
    ) -> None:
        """Should return 404 when accessing another user's conversation."""
        # Create another user and their conversation
        other_user = test_database.get_or_create_user(email="other@example.com", name="Other")
        other_conv = test_database.create_conversation(other_user.id)

        # Try to access with original test user's auth
        from src.auth.jwt_auth import create_token

        test_user = test_database.get_or_create_user(email="test@example.com", name="Test")
        token = create_token(test_user)

        response = client.get(
            f"/api/conversations/{other_conv.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient, test_conversation: Conversation) -> None:
        """Should return 401 without authentication."""
        response = client.get(f"/api/conversations/{test_conversation.id}")
        assert response.status_code == 401


class TestUpdateConversation:
    """Tests for PATCH /api/conversations/<conv_id> endpoint."""

    def test_updates_title(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should update conversation title."""
        response = client.patch(
            f"/api/conversations/{test_conversation.id}",
            headers=auth_headers,
            json={"title": "New Title"},
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "updated"

    def test_updates_model(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should update conversation model."""
        response = client.patch(
            f"/api/conversations/{test_conversation.id}",
            headers=auth_headers,
            json={"model": "gemini-3.1-pro-preview"},
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "updated"

    def test_rejects_invalid_model(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return 400 for invalid model."""
        response = client.patch(
            f"/api/conversations/{test_conversation.id}",
            headers=auth_headers,
            json={"model": "invalid-model"},
        )

        assert response.status_code == 400

    def test_returns_404_for_nonexistent(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 for non-existent conversation."""
        response = client.patch(
            "/api/conversations/nonexistent-id",
            headers=auth_headers,
            json={"title": "Test"},
        )

        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient, test_conversation: Conversation) -> None:
        """Should return 401 without authentication."""
        response = client.patch(
            f"/api/conversations/{test_conversation.id}",
            json={"title": "Test"},
        )
        assert response.status_code == 401


class TestDeleteConversation:
    """Tests for DELETE /api/conversations/<conv_id> endpoint."""

    def test_deletes_conversation(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should delete conversation."""
        response = client.delete(
            f"/api/conversations/{test_conversation.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200

        # Verify it's gone
        get_response = client.get(
            f"/api/conversations/{test_conversation.id}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    def test_returns_404_for_nonexistent(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 for non-existent conversation."""
        response = client.delete(
            "/api/conversations/nonexistent-id",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient, test_conversation: Conversation) -> None:
        """Should return 401 without authentication."""
        response = client.delete(f"/api/conversations/{test_conversation.id}")
        assert response.status_code == 401


class TestArchiveConversation:
    """Tests for POST /api/conversations/<conv_id>/archive endpoint."""

    def test_archive_conversation(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should archive a conversation and return status archived."""
        response = client.post(
            f"/api/conversations/{test_conversation.id}/archive",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "archived"

    def test_archive_nonexistent_returns_404(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 when archiving a nonexistent conversation."""
        response = client.post(
            "/api/conversations/nonexistent-id/archive",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_archive_requires_auth(
        self, client: FlaskClient, test_conversation: Conversation
    ) -> None:
        """Should return 401 without authentication."""
        response = client.post(f"/api/conversations/{test_conversation.id}/archive")
        assert response.status_code == 401

    def test_archived_excluded_from_list(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should exclude archived conversation from GET /api/conversations."""
        # Archive the conversation
        client.post(
            f"/api/conversations/{test_conversation.id}/archive",
            headers=auth_headers,
        )

        # The conversation should not appear in the regular list
        response = client.get("/api/conversations", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        returned_ids = [c["id"] for c in data["conversations"]]
        assert test_conversation.id not in returned_ids


class TestUnarchiveConversation:
    """Tests for POST /api/conversations/<conv_id>/unarchive endpoint."""

    def test_unarchive_conversation(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Should unarchive a conversation and return status unarchived."""
        # Archive first so we can unarchive
        test_database.archive_conversation(test_conversation.id, test_conversation.user_id)

        response = client.post(
            f"/api/conversations/{test_conversation.id}/unarchive",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "unarchived"

    def test_unarchive_nonexistent_returns_404(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 when unarchiving a nonexistent conversation."""
        response = client.post(
            "/api/conversations/nonexistent-id/unarchive",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_unarchive_requires_auth(
        self, client: FlaskClient, test_conversation: Conversation
    ) -> None:
        """Should return 401 without authentication."""
        response = client.post(f"/api/conversations/{test_conversation.id}/unarchive")
        assert response.status_code == 401


class TestListArchivedConversations:
    """Tests for GET /api/conversations/archived endpoint."""

    def test_list_archived(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return archived conversations after archiving one."""
        # Archive the test conversation
        client.post(
            f"/api/conversations/{test_conversation.id}/archive",
            headers=auth_headers,
        )

        response = client.get("/api/conversations/archived", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "conversations" in data
        assert "pagination" in data
        returned_ids = [c["id"] for c in data["conversations"]]
        assert test_conversation.id in returned_ids
        # Each archived conversation should have archived flag set
        archived_conv = next(c for c in data["conversations"] if c["id"] == test_conversation.id)
        assert archived_conv["archived"] is True

    def test_list_archived_empty(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should return empty list when no conversations are archived."""
        response = client.get("/api/conversations/archived", headers=auth_headers)

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["conversations"] == []

    def test_list_archived_requires_auth(self, client: FlaskClient) -> None:
        """Should return 401 without authentication."""
        response = client.get("/api/conversations/archived")
        assert response.status_code == 401
