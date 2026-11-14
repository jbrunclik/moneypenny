"""Integration tests for POST /api/conversations/<conv_id>/chat/stop."""

from flask.testing import FlaskClient

from src.agent.cancellation import adopt_pending_stop, stop_requested
from src.db.models import Database
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

    def test_a_stop_before_the_turn_is_acknowledged_reaches_it(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        """Stop pressed before the stream's first event: the client knows only
        its own message id. The turn picks the Stop up when it saves its reply
        placeholder - before, it kept generating while the client showed "Not
        sent" (Oct 2026 single-device audit)."""
        client_id = "6f1d2c3b-4a59-4e8d-9c7b-1a2b3c4d5e6f"
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/stop",
            json={"client_message_id": client_id},
            headers=auth_headers,
        )
        assert response.status_code == 200

        # The turn for that message starts and saves its reply placeholder
        assert adopt_pending_stop(test_user.id, test_conversation.id, client_id, "reply-1")
        assert stop_requested(test_user.id, test_conversation.id, "reply-1") is True

    def test_a_stop_for_another_message_does_not_stop_this_turn(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        client.post(
            f"/api/conversations/{test_conversation.id}/chat/stop",
            json={"client_message_id": "6f1d2c3b-4a59-4e8d-9c7b-1a2b3c4d5e6f"},
            headers=auth_headers,
        )
        other = "0b0b0b0b-4a59-4e8d-9c7b-1a2b3c4d5e6f"
        assert not adopt_pending_stop(test_user.id, test_conversation.id, other, "reply-2")
        assert stop_requested(test_user.id, test_conversation.id, "reply-2") is False

    def test_a_stop_by_message_id_reaches_a_turn_already_running(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        """The turn saved its placeholder, but its first event had not reached
        the client when Stop was pressed."""
        client_id = "6f1d2c3b-4a59-4e8d-9c7b-1a2b3c4d5e6f"
        test_database.add_message(test_conversation.id, "user", "Plan it", message_id=client_id)
        reply_id = test_database.add_message(test_conversation.id, "assistant", "").id

        client.post(
            f"/api/conversations/{test_conversation.id}/chat/stop",
            json={"client_message_id": client_id},
            headers=auth_headers,
        )

        assert stop_requested(test_user.id, test_conversation.id, reply_id) is True

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
