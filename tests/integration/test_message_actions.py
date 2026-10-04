"""Action messages: what a message sent on the user's behalf was."""

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from flask.testing import FlaskClient

from src.agent.deep_research.offer import build_offer
from src.api.schemas.common import MessageRole

if TYPE_CHECKING:
    from src.db.models import Conversation, Database


def _stream(
    client: FlaskClient, headers: dict[str, str], conv_id: str, body: dict[str, Any]
) -> Any:
    with patch("src.api.helpers.chat_turn.ChatAgent") as agent_cls:
        agent = MagicMock()

        def events(*_a: Any, **_k: Any) -> Any:
            yield {
                "type": "final",
                "content": "reply",
                "result_messages": [],
                "tool_results": [],
                "usage_info": {},
            }

        agent.stream_chat_events = events
        agent_cls.return_value = agent
        response = client.post(
            f"/api/conversations/{conv_id}/chat/stream", headers=headers, json=body
        )
        response.get_data()  # drain the stream: the turn saves at its end
        return response


def _user_messages(client: FlaskClient, headers: dict[str, str], conv_id: str) -> list[Any]:
    data = client.get(f"/api/conversations/{conv_id}/messages", headers=headers).get_json()
    return [m for m in data["messages"] if m["role"] == "user"]


VERIFY = {"type": "verify_claim", "source_message_id": "a1", "claim_index": 2, "quote": "X"}


class TestActions:
    def test_a_verify_claim_action_is_stored_and_returned(
        self, client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
    ) -> None:
        body = {"message": "Look up and verify: X", "action": VERIFY}
        assert _stream(client, auth_headers, test_conversation.id, body).status_code == 200

        [user] = _user_messages(client, auth_headers, test_conversation.id)
        assert user["action"] == VERIFY
        assert user["content"] == "Look up and verify: X"

    def test_plain_messages_have_no_action(
        self, client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
    ) -> None:
        _stream(client, auth_headers, test_conversation.id, {"message": "hi"})
        [user] = _user_messages(client, auth_headers, test_conversation.id)
        assert user.get("action") is None

    def test_an_unknown_action_type_is_rejected(
        self, client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
    ) -> None:
        body = {"message": "x", "action": {"type": "launch_rockets"}}
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/stream",
            headers=auth_headers,
            json=body,
        )
        assert response.status_code == 400

    def test_a_deep_research_start_stores_its_action(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        offer = build_offer({"question": "Q", "context": "", "sub_questions": ["a", "b"]})
        offer_id = test_database.add_message(
            test_conversation.id, MessageRole.ASSISTANT, "quick", research={"offer": offer}
        ).id
        body = {
            "message": "Start deep research",
            "deep_research": {"offer_message_id": offer_id, "sub_questions": ["a", "b", "c"]},
        }
        with patch("src.api.helpers.stream_producer.run_deep_research") as run:
            run.return_value = iter(
                [
                    {
                        "type": "final",
                        "content": "report",
                        "result_messages": [],
                        "tool_results": [],
                        "usage_info": {},
                    }
                ]
            )
            _stream(client, auth_headers, test_conversation.id, body)

        [user] = _user_messages(client, auth_headers, test_conversation.id)
        assert user["action"]["type"] == "deep_research"
        assert user["action"]["offer_message_id"] == offer_id
        assert user["action"]["items"] == 3
        assert user["action"]["minutes"] > 0

    def test_a_deep_research_action_without_a_start_is_rejected(
        self, client: FlaskClient, auth_headers: dict[str, str], test_conversation: Conversation
    ) -> None:
        """It would render a "Deep research started" row for a run that never ran."""
        action = {"type": "deep_research", "offer_message_id": "x", "items": 3, "minutes": 5}
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/stream",
            headers=auth_headers,
            json={"message": "Start deep research", "action": action},
        )
        assert response.status_code == 400
