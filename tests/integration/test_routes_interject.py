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

    def test_interjection_sorts_before_the_reply_it_steers(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        """The reply in flight takes the steering into account, so history
        reads question -> steering -> reply. Stored after the placeholder,
        the turn ended on a user message: no regenerate/continue on the reply
        (continue requires an assistant last), live and after a reload."""
        test_database.add_message(test_conversation.id, "user", "Compare the plans")
        placeholder = test_database.add_message(test_conversation.id, "assistant", "")

        client.post(
            f"/api/conversations/{test_conversation.id}/chat/interject",
            json={"message": "Only the 2025 ones"},
            headers=auth_headers,
        )
        test_database.update_message_content(placeholder.id, "Here is the comparison")

        messages = test_database.get_messages(test_conversation.id)
        assert [m.content for m in messages] == [
            "Compare the plans",
            "Only the 2025 ones",
            "Here is the comparison",
        ]

    def test_interjection_after_the_turn_finished_stays_last(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        test_database.add_message(test_conversation.id, "user", "Q")
        test_database.add_message(test_conversation.id, "assistant", "A")

        client.post(
            f"/api/conversations/{test_conversation.id}/chat/interject",
            json={"message": "Too late"},
            headers=auth_headers,
        )

        assert test_database.get_messages(test_conversation.id)[-1].content == "Too late"

    def test_interjection_is_stored_under_the_client_id(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        """The bubble the client rendered and the saved message share an id:
        otherwise every steered turn's sync echo looked like a vanished
        message and forced a full re-render (and a later delete 404'd)."""
        client_id = "0b6f8f2e-6d0c-4f7a-9a8e-2f1d3c4b5a69"
        for _ in range(2):  # a retry is idempotent
            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/interject",
                json={"message": "Steer it", "client_message_id": client_id},
                headers=auth_headers,
            )
            assert response.status_code == 200

        steering = [
            m for m in test_database.get_messages(test_conversation.id) if m.content == "Steer it"
        ]
        assert [m.id for m in steering] == [client_id]

    def test_rejects_a_non_uuid_client_id(
        self, client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
    ) -> None:
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/interject",
            json={"message": "x", "client_message_id": "not-a-uuid"},
            headers=auth_headers,
        )
        assert response.status_code == 400

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
