"""Integration tests for POST /api/conversations/<conv_id>/chat/interject."""

from unittest.mock import patch

from flask.testing import FlaskClient

from src.agent.interjection import KV_NAMESPACE, pop_interjection
from src.db.models import Database
from src.db.models.dataclasses import Conversation, User


class TestChatInterject:
    def test_stores_interjection_and_persists_user_message(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/interject",
            json={"message": "Stop - use the 2025 numbers"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.get_json()["status"] == "interjected"

        # Steering text is retrievable (and consumed) by the graph hook
        assert pop_interjection(test_user.id, test_conversation.id) == "Stop - use the 2025 numbers"
        # Pop is one-shot
        assert pop_interjection(test_user.id, test_conversation.id) is None

        # Also persisted as a visible user message for future turns
        messages = test_database.get_messages(test_conversation.id)
        assert any(
            m.content == "Stop - use the 2025 numbers" and m.role.value == "user" for m in messages
        )

    def test_rejects_unknown_conversation(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.post(
            "/api/conversations/nonexistent/chat/interject",
            json={"message": "hello"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_rejects_empty_message(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/interject",
            json={"message": ""},
            headers=auth_headers,
        )
        assert response.status_code == 400

    def test_requires_auth(self, client: FlaskClient, test_conversation: Conversation) -> None:
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/interject",
            json={"message": "hi"},
        )
        assert response.status_code == 401

    def test_new_stream_clears_stale_interjection(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        """A leftover interjection from a finished turn must not steer the
        next turn - the stream route clears it up front."""
        test_database.kv_set(test_user.id, KV_NAMESPACE, test_conversation.id, "stale steering")

        # Starting a new stream clears the leftover before generating. The
        # real generator spawns a producer thread that would race test
        # teardown, and the clear happens in the route body before the
        # generator exists - stub it out.
        with patch(
            "src.api.helpers.chat_streaming.create_stream_generator",
            return_value=iter(()),
        ):
            client.post(
                f"/api/conversations/{test_conversation.id}/chat/stream",
                json={"message": "new turn"},
                headers=auth_headers,
            )

        assert pop_interjection(test_user.id, test_conversation.id) is None
