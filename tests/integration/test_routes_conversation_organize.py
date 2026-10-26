"""Integration tests for organizing conversations: archive, unarchive, the archived list, pin and unpin."""

import json
from typing import TYPE_CHECKING

from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Conversation, Database


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


class TestPinnedConversations:
    def _create(self, test_database, test_user, title):
        return test_database.create_conversation(
            user_id=test_user.id, title=title, model="gemini-3.8-flash"
        )

    def test_pin_and_unpin(self, client, auth_headers, test_conversation) -> None:
        response = client.post(
            f"/api/conversations/{test_conversation.id}/pin", headers=auth_headers
        )
        assert response.status_code == 200

        listed = client.get("/api/conversations", headers=auth_headers).get_json()
        pinned_ids = [c["id"] for c in listed["pinned_conversations"]]
        assert test_conversation.id in pinned_ids
        # Pinned conversations are not duplicated in the paginated portion
        assert test_conversation.id not in [c["id"] for c in listed["conversations"]]

        response = client.post(
            f"/api/conversations/{test_conversation.id}/unpin", headers=auth_headers
        )
        assert response.status_code == 200
        listed = client.get("/api/conversations", headers=auth_headers).get_json()
        assert listed["pinned_conversations"] == []
        assert test_conversation.id in [c["id"] for c in listed["conversations"]]

    def test_pinned_carry_previews_and_flag(
        self, client, auth_headers, test_conversation, test_database
    ) -> None:
        test_database.add_message(test_conversation.id, "user", "pinned content")
        client.post(f"/api/conversations/{test_conversation.id}/pin", headers=auth_headers)

        listed = client.get("/api/conversations", headers=auth_headers).get_json()
        pinned = listed["pinned_conversations"][0]
        assert pinned["pinned"] is True
        assert pinned["last_message_preview"] == "pinned content"

    def test_pin_unknown_conversation_404(self, client, auth_headers) -> None:
        response = client.post("/api/conversations/nope/pin", headers=auth_headers)
        assert response.status_code == 404
