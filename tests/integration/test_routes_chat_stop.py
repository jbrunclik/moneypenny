"""Integration tests for POST /api/conversations/<conv_id>/chat/stop."""

from flask.testing import FlaskClient

from src.agent.cancellation import stop_requested
from src.db.models.dataclasses import Conversation, User


class TestChatStop:
    def test_sets_the_stop_flag(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/stop",
            json={"message_id": "msg-1"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.get_json() == {"status": "stopping"}
        assert stop_requested(test_user.id, test_conversation.id, "msg-1") is True

    def test_requires_the_turns_message_id(
        self, client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
    ) -> None:
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/stop", json={}, headers=auth_headers
        )
        assert response.status_code == 400

    def test_rejects_unknown_conversation(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/api/conversations/nonexistent/chat/stop",
            json={"message_id": "msg-1"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient, test_conversation: Conversation) -> None:
        response = client.post(f"/api/conversations/{test_conversation.id}/chat/stop")
        assert response.status_code == 401
