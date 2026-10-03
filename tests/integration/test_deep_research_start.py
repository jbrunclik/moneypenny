"""Starting a deep-research run from an offer, and declining one."""

import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
from flask.testing import FlaskClient

from src.agent.deep_research.offer import build_offer
from src.api.schemas.common import MessageRole

if TYPE_CHECKING:
    from src.db.models import Conversation, Database


def _offer(db: Database, conv_id: str, status: str = "offered") -> str:
    offer = build_offer({"question": "Q", "context": "Praha", "sub_questions": ["a", "b"]})
    offer["status"] = status
    return db.add_message(
        conv_id, MessageRole.ASSISTANT, "quick answer", research={"offer": offer}
    ).id


def _stream(
    client: FlaskClient, headers: dict[str, str], conv_id: str, body: dict[str, Any]
) -> Any:
    with patch("src.api.helpers.chat_turn.ChatAgent") as agent_cls:
        agent = MagicMock()

        def events(*_a: Any, **_k: Any) -> Any:
            yield {
                "type": "final",
                "content": "report",
                "result_messages": [],
                "tool_results": [],
                "usage_info": {},
            }

        agent.stream_chat_events = events
        agent_cls.return_value = agent
        return client.post(f"/api/conversations/{conv_id}/chat/stream", headers=headers, json=body)


def _start(offer_id: str, items: list[str], context: str = "Praha") -> dict[str, Any]:
    return {
        "message": "Start deep research",
        "deep_research": {"offer_message_id": offer_id, "sub_questions": items, "context": context},
    }


class TestStart:
    def test_valid_start_marks_the_offer_started_with_the_final_plan(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        offer_id = _offer(test_database, test_conversation.id)

        response = _stream(
            client, auth_headers, test_conversation.id, _start(offer_id, ["a", "c", "d"])
        )

        assert response.status_code == 200
        offer = test_database.get_message_by_id(offer_id).research["offer"]
        assert offer["status"] == "started"
        assert offer["final_sub_questions"] == ["a", "c", "d"]
        assert offer["sub_questions"] == ["a", "b"]
        assert set(offer["final_estimate"]) == {"minutes", "cost_czk"}

    def test_start_logs_the_edits_and_time_to_decide(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        offer_id = _offer(test_database, test_conversation.id)

        with caplog.at_level(logging.INFO):
            _stream(client, auth_headers, test_conversation.id, _start(offer_id, ["a", "c", "d"]))

        record = next(r for r in caplog.records if r.getMessage() == "Deep research started")
        assert (record.items, record.added, record.removed) == (3, 2, 1)
        assert record.context_edited is False
        assert record.decision_seconds >= 0

    def test_invalid_plans_are_rejected_and_nothing_starts(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        offer_id = _offer(test_database, test_conversation.id)
        for items in ([], [str(i) for i in range(9)], ["x" * 2000]):
            response = _stream(client, auth_headers, test_conversation.id, _start(offer_id, items))
            assert response.status_code == 400, items
        assert test_database.get_message_by_id(offer_id).research["offer"]["status"] == "offered"

    def test_offer_from_another_conversation_is_not_found(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
        test_user: Any,
    ) -> None:
        other = test_database.create_conversation(test_user.id, "Other")
        offer_id = _offer(test_database, other.id)

        response = _stream(client, auth_headers, test_conversation.id, _start(offer_id, ["a"]))

        assert response.status_code == 404

    def test_an_offer_already_decided_conflicts(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        for status in ("started", "declined"):
            offer_id = _offer(test_database, test_conversation.id, status)
            response = _stream(client, auth_headers, test_conversation.id, _start(offer_id, ["a"]))
            assert response.status_code == 409, status

    def test_batch_endpoint_refuses_deep_research(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        offer_id = _offer(test_database, test_conversation.id)

        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/batch",
            headers=auth_headers,
            json=_start(offer_id, ["a"]),
        )

        assert response.status_code == 400


class TestDecline:
    def test_decline_marks_the_offer(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        offer_id = _offer(test_database, test_conversation.id)

        response = client.patch(
            f"/api/messages/{offer_id}/research-offer",
            headers=auth_headers,
            json={"status": "declined"},
        )

        assert response.status_code == 200
        assert test_database.get_message_by_id(offer_id).research["offer"]["status"] == "declined"

    def test_decline_logs_time_to_decide(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        offer_id = _offer(test_database, test_conversation.id)

        with caplog.at_level(logging.INFO):
            client.patch(
                f"/api/messages/{offer_id}/research-offer",
                headers=auth_headers,
                json={"status": "declined"},
            )

        record = next(r for r in caplog.records if r.getMessage() == "Deep research declined")
        assert record.decision_seconds >= 0
        assert record.sub_questions == 2

    def test_other_statuses_are_rejected(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        offer_id = _offer(test_database, test_conversation.id)

        response = client.patch(
            f"/api/messages/{offer_id}/research-offer",
            headers=auth_headers,
            json={"status": "started"},
        )

        assert response.status_code == 400
