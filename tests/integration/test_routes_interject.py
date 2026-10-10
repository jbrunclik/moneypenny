"""Integration tests for steering a turn in flight: POST .../chat/interject,
and a send from another device while the conversation's turn is running."""

import json
import threading
import time
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

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


def _sse_events(body: bytes) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data: ") :])
        for line in body.decode().splitlines()
        if line.startswith("data: ")
    ]


class TestSendDuringAnotherDevicesTurn:
    """Two devices sending into one conversation at once used to start two
    parallel turns whose messages and replies interleaved. A plain text send
    while a turn is live steers that turn instead."""

    CLIENT_ID = "6f1d2c3b-4a59-4e8d-9c7b-1a2b3c4d5e6f"

    @staticmethod
    def _running_turn(db: Database, conv_id: str) -> str:
        """Another device's turn in flight: its question and empty reply."""
        db.add_message(conv_id, "user", "Compare the plans")
        return db.add_message(conv_id, "assistant", "").id

    def _stream(
        self, client: FlaskClient, headers: dict[str, str], conv_id: str, **body: Any
    ) -> tuple[Any, MagicMock]:
        """POST the stream route; the normal turn's generator is stubbed (its
        producer thread would race teardown) - called means a new turn."""
        payload = {"message": "Only the 2025 ones", "client_message_id": self.CLIENT_ID, **body}
        with patch(
            "src.api.helpers.chat_streaming.create_stream_generator", return_value=iter(())
        ) as new_turn:
            response = client.post(
                f"/api/conversations/{conv_id}/chat/stream", json=payload, headers=headers
            )
        return response, new_turn

    def test_stream_send_steers_the_running_turn(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        reply_id = self._running_turn(test_database, test_conversation.id)

        response, new_turn = self._stream(client, auth_headers, test_conversation.id)

        assert response.status_code == 200
        new_turn.assert_not_called()
        events = _sse_events(response.data)
        assert events[0] == {"type": "user_message_saved", "user_message_id": self.CLIENT_ID}
        assert events[1]["type"] == "interjected"
        assert events[1]["message_id"] == reply_id
        # (the reply in flight counts: it is the turn's reply)
        assert events[1]["message_count"] == 3
        assert pop_interjection(test_user.id, test_conversation.id) == "Only the 2025 ones"
        # One turn: question -> steering -> the reply that takes it into account
        test_database.update_message_content(reply_id, "Here is the comparison")
        assert [m.content for m in test_database.get_messages(test_conversation.id)] == [
            "Compare the plans",
            "Only the 2025 ones",
            "Here is the comparison",
        ]

    def test_a_finished_turn_starts_a_new_one(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        reply_id = self._running_turn(test_database, test_conversation.id)
        test_database.journal_append_events(reply_id, [(1, json.dumps({"type": "stream_end"}))])

        _, new_turn = self._stream(client, auth_headers, test_conversation.id)

        new_turn.assert_called_once()

    def test_a_stalled_turn_starts_a_new_one(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        """A worker that died mid-turn left no end marker: steering a dead
        turn would leave the send unanswered."""
        reply_id = self._running_turn(test_database, test_conversation.id)
        with patch("src.db.models.stream_journal.time.time", return_value=time.time() - 1_000):
            test_database.journal_append_events(reply_id, [(1, json.dumps({"type": "token"}))])

        _, new_turn = self._stream(client, auth_headers, test_conversation.id)

        new_turn.assert_called_once()

    def test_an_old_unjournaled_placeholder_starts_a_new_one(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        reply_id = self._running_turn(test_database, test_conversation.id)
        test_database.set_message_created_at(reply_id, datetime.now() - timedelta(seconds=400))

        _, new_turn = self._stream(client, auth_headers, test_conversation.id)

        new_turn.assert_called_once()

    def test_a_live_journal_keeps_steering(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        reply_id = self._running_turn(test_database, test_conversation.id)
        test_database.set_message_created_at(reply_id, datetime.now() - timedelta(seconds=400))
        test_database.journal_append_events(reply_id, [(1, json.dumps({"type": "token"}))])

        _, new_turn = self._stream(client, auth_headers, test_conversation.id)

        new_turn.assert_not_called()

    def test_sends_that_need_their_own_turn_still_get_one(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        self._running_turn(test_database, test_conversation.id)
        for extra in ({"force_tools": ["web_search"]}, {"rerun_mode": "continue"}):
            response, _ = self._stream(
                client, auth_headers, test_conversation.id, client_message_id=None, **extra
            )
            assert all(e["type"] != "interjected" for e in _sse_events(response.data))
            assert pop_interjection(test_user.id, test_conversation.id) is None

    def test_a_retry_of_a_steering_send_is_a_duplicate(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        self._running_turn(test_database, test_conversation.id)
        self._stream(client, auth_headers, test_conversation.id)

        response, new_turn = self._stream(client, auth_headers, test_conversation.id)

        assert response.status_code == 409
        new_turn.assert_not_called()

    def test_batch_send_steers_and_answers_with_the_running_reply(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_conversation: Conversation,
    ) -> None:
        reply_id = self._running_turn(test_database, test_conversation.id)
        # The other device's turn finishes a moment later
        finish = threading.Timer(
            0.3, lambda: test_database.update_message_content(reply_id, "Here is the comparison")
        )
        finish.start()
        try:
            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/batch",
                json={"message": "Only the 2025 ones", "client_message_id": self.CLIENT_ID},
                headers=auth_headers,
            )
        finally:
            finish.join()

        assert response.status_code == 200
        data = response.get_json()
        assert data["id"] == reply_id
        assert data["content"] == "Here is the comparison"
        assert data["user_message_id"] == self.CLIENT_ID
        assert len(test_database.get_messages(test_conversation.id)) == 3


class TestInterjectionClearedAtTurnEnd:
    """Steering is consumed only between tool rounds. One that arrived after
    the last round was never popped: its kv slot stayed until the
    conversation's NEXT turn - forever for a deleted one (it showed up on
    the Data page long after)."""

    def test_stream_turn_end_clears_an_unconsumed_interjection(
        self,
        client: FlaskClient,  # patches the global db onto the test database
        test_database: Database,
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        from src.agent.interjection import save_interjection
        from src.api.helpers.chat_turn import TurnContext
        from src.api.helpers.stream_producer import stream_events

        saved: list[bool] = []

        class _Agent:
            def stream_chat_events(self, *args: Any, **kwargs: Any) -> Any:
                yield {"type": "token", "text": "Answer"}
                # Arrives while the final answer streams: nothing pops it
                save_interjection(test_user.id, test_conversation.id, "and the 2025 ones")
                saved.append(True)
                yield {"type": "token", "text": " done"}

        q: Any = __import__("queue").Queue()
        stream_events(
            _Agent(),  # type: ignore[arg-type]
            q,
            {"ready": False, "saved": False},
            TurnContext(
                request_id="req-1",
                conv_id=test_conversation.id,
                user_id=test_user.id,
                message_text="hello",
                user_name="Alice",
            ),
        )

        assert saved == [True]
        assert test_database.kv_get(test_user.id, KV_NAMESPACE, test_conversation.id) is None

    def test_batch_turn_end_clears_an_unconsumed_interjection(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
        test_conversation: Conversation,
    ) -> None:
        from src.agent.interjection import save_interjection

        def _chat_batch(**_: Any) -> tuple[str, list[Any], dict[str, int], list[Any]]:
            save_interjection(test_user.id, test_conversation.id, "and the 2025 ones")
            return ("Answer", [], {"input_tokens": 1, "output_tokens": 1}, [])

        with patch("src.api.helpers.chat_turn.ChatAgent") as agent_class:
            agent_class.return_value.chat_batch.side_effect = _chat_batch
            response = client.post(
                f"/api/conversations/{test_conversation.id}/chat/batch",
                headers=auth_headers,
                json={"message": "Compare the plans"},
            )

        assert response.status_code == 200
        assert test_database.kv_get(test_user.id, KV_NAMESPACE, test_conversation.id) is None
