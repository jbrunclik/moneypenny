"""Starting a deep-research run from its card (a deep_research proposal),
by its Start button or a typed yes, and declining one."""

import json
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
from flask.testing import FlaskClient

from src.agent.deep_research.offer import build_offer, file_offer_card
from src.enums import MessageRole

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, Proposal


def _card(db: Database, conv: Conversation, state: str = "pending", **offer_args: Any) -> Proposal:
    """An offer's card under its reply (a follow-up when kind='followup')."""
    kind = offer_args.pop("kind", "initial")
    offer = build_offer(
        {"question": "Q", "context": "Praha", "sub_questions": ["a", "b"], **offer_args}, kind
    )
    card = file_offer_card(offer, conv.id, conv.user_id, request_id="offer-turn")
    reply = db.add_message(conv.id, MessageRole.ASSISTANT, "quick answer")
    db.link_proposals("offer-turn", reply.id)
    if state != "pending":
        db.claim_proposal(card.id, state, 0 if state == "approved" else None, "button")
    stored = db.get_proposal(card.id, conv.user_id)
    assert stored is not None
    return stored


def _final_events(*_a: Any, **_k: Any) -> Any:
    yield {
        "type": "final",
        "content": "report",
        "result_messages": [],
        "tool_results": [],
        "usage_info": {},
    }


def _stream(
    client: FlaskClient, headers: dict[str, str], conv_id: str, body: dict[str, Any]
) -> Any:
    # A start turn runs run_deep_research, not the agent: fake it too, and
    # drain the response inside the patches. The real pipeline (subagents
    # calling out with the fake key) kept running after the test and opened
    # the NEXT test's fresh database - a "database is locked" CI flake.
    with (
        patch("src.api.helpers.chat_turn.ChatAgent") as agent_cls,
        patch(
            "src.api.helpers.stream_producer.run_deep_research",
            MagicMock(side_effect=_final_events),
        ) as run,
    ):
        agent = MagicMock()
        agent.stream_chat_events = _final_events
        agent_cls.return_value = agent
        response = client.post(
            f"/api/conversations/{conv_id}/chat/stream", headers=headers, json=body
        )
        response.get_data()
        response.research_ran = run  # type: ignore[attr-defined]
        return response


def _start(card_id: str, items: list[str], context: str = "Praha") -> dict[str, Any]:
    return {
        "message": "Start deep research",
        "deep_research": {"proposal_id": card_id, "sub_questions": items, "context": context},
    }


def _payload(db: Database, card: Proposal) -> dict[str, Any]:
    stored = db.get_proposal(card.id, card.user_id)
    assert stored is not None and stored.chosen is not None
    return dict(stored.options[stored.chosen]["payload"])


class TestStart:
    def test_start_claims_the_card_with_the_final_plan(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        card = _card(test_database, test_conversation)

        response = _stream(
            client, auth_headers, test_conversation.id, _start(card.id, ["a", "c", "d"])
        )

        assert response.status_code == 200
        stored = test_database.get_proposal(card.id, card.user_id)
        assert stored is not None and (stored.state, stored.resolved_by) == ("approved", "button")
        payload = _payload(test_database, card)
        assert payload["final_sub_questions"] == ["a", "c", "d"]
        assert payload["sub_questions"] == ["a", "b"]
        assert set(payload["final_estimate"]) == {"minutes", "cost_czk"}

    def test_start_logs_the_edits_and_time_to_decide(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        card = _card(test_database, test_conversation)

        with caplog.at_level(logging.INFO):
            _stream(client, auth_headers, test_conversation.id, _start(card.id, ["a", "c", "d"]))

        record = next(r for r in caplog.records if r.getMessage() == "Deep research started")
        assert (record.items, record.added, record.removed) == (3, 2, 1)
        assert record.context_edited is False
        assert record.decision_seconds >= 0
        assert record.resolved_by == "button"
        resolved = next(r for r in caplog.records if r.getMessage() == "Proposal resolved")
        assert (resolved.kind, resolved.state) == ("deep_research", "approved")

    def test_invalid_plans_are_rejected_and_nothing_starts(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        card = _card(test_database, test_conversation)
        for items in ([], [str(i) for i in range(9)], ["x" * 2000]):
            response = _stream(client, auth_headers, test_conversation.id, _start(card.id, items))
            assert response.status_code == 400, items
        stored = test_database.get_proposal(card.id, card.user_id)
        assert stored is not None and stored.state == "pending"

    def test_disabled_deep_research_refuses_an_existing_offer(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        # The kill switch must stop runs, not only new offers
        card = _card(test_database, test_conversation)

        with patch("src.api.helpers.chat_turn.Config.DEEP_RESEARCH_ENABLED", False):
            response = _stream(client, auth_headers, test_conversation.id, _start(card.id, ["a"]))

        assert response.status_code == 400
        assert "turned off" in response.get_json()["error"]["message"]
        stored = test_database.get_proposal(card.id, card.user_id)
        assert stored is not None and stored.state == "pending"
        assert len(test_database.get_messages(test_conversation.id)) == 1

    def test_a_card_from_another_conversation_is_not_found(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
        test_user: Any,
    ) -> None:
        other = test_database.create_conversation(test_user.id, "Other")
        card = _card(test_database, other)

        response = _stream(client, auth_headers, test_conversation.id, _start(card.id, ["a"]))

        assert response.status_code == 404

    def test_a_card_already_answered_conflicts(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        # 400, not 409: the client reads 409 as "your message already landed"
        for state in ("approved", "declined", "expired"):
            card = _card(test_database, test_conversation, state)
            response = _stream(client, auth_headers, test_conversation.id, _start(card.id, ["a"]))
            assert response.status_code == 400, state
            assert "already" in response.get_json()["error"]["message"], state

    def test_a_retry_of_a_start_that_landed_is_a_duplicate(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        card = _card(test_database, test_conversation)
        body = {
            **_start(card.id, ["a"]),
            "client_message_id": "0b7f3c1e-1111-4222-8333-944455556666",
        }
        assert _stream(client, auth_headers, test_conversation.id, body).status_code == 200

        retry = _stream(client, auth_headers, test_conversation.id, body)

        assert retry.status_code == 409

    def test_batch_endpoint_refuses_deep_research(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        card = _card(test_database, test_conversation)

        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/batch",
            headers=auth_headers,
            json=_start(card.id, ["a"]),
        )

        assert response.status_code == 400

    def test_the_approve_button_endpoint_refuses_a_research_card(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """Starting is a turn (its progress streams): only Start or a typed yes."""
        card = _card(test_database, test_conversation)

        response = client.post(f"/api/proposals/{card.id}/approve", headers=auth_headers, json={})

        assert response.status_code == 400
        stored = test_database.get_proposal(card.id, card.user_id)
        assert stored is not None and stored.state == "pending"


class TestTypedStart:
    def test_a_typed_yes_makes_the_turn_the_run(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        card = _card(test_database, test_conversation)

        response = _stream(client, auth_headers, test_conversation.id, {"message": "ano"})

        assert response.status_code == 200
        response.research_ran.assert_called_once()  # type: ignore[attr-defined]
        plan = response.research_ran.call_args.args[0]  # type: ignore[attr-defined]
        assert plan.sub_questions == ["a", "b"] and plan.previous_report is None
        stored = test_database.get_proposal(card.id, card.user_id)
        assert stored is not None and (stored.state, stored.resolved_by) == ("approved", "typed")

    def test_a_typed_start_is_shown_at_once_and_links_to_its_report(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        """The run takes minutes: the card shows started from the first event,
        and the "yes" becomes the run's action row (its report link)."""
        card = _card(test_database, test_conversation)

        response = _stream(client, auth_headers, test_conversation.id, {"message": "ano"})

        events = [
            json.loads(line[6:])
            for line in response.get_data(as_text=True).splitlines()
            if line.startswith("data: ")
        ]
        saved = next(e for e in events if e["type"] == "user_message_saved")
        assert [(p["id"], p["state"]) for p in saved["answered_proposals"]] == [
            (card.id, "approved")
        ]
        assert saved["action"]["type"] == "deep_research"
        assert saved["action"]["offer_message_id"] == card.message_id
        stored = test_database.get_message_by_id(saved["user_message_id"])
        assert stored is not None and stored.action == saved["action"]

    def test_a_typed_yes_on_a_followup_passes_the_report(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        _card(test_database, test_conversation, kind="followup")

        response = _stream(client, auth_headers, test_conversation.id, {"message": "yes"})

        plan = response.research_ran.call_args.args[0]  # type: ignore[attr-defined]
        assert plan.previous_report == "quick answer"

    def test_another_message_expires_the_card_and_runs_a_normal_turn(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        card = _card(test_database, test_conversation)

        response = _stream(client, auth_headers, test_conversation.id, {"message": "Why?"})

        response.research_ran.assert_not_called()  # type: ignore[attr-defined]
        stored = test_database.get_proposal(card.id, card.user_id)
        assert stored is not None and stored.state == "expired"

    def test_in_batch_mode_a_typed_yes_leaves_the_card_for_its_start_button(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        card = _card(test_database, test_conversation)

        with patch("src.api.helpers.chat_turn.ChatAgent") as agent_cls:
            agent_cls.return_value.chat_batch.return_value = ("ok", [], {}, [])
            client.post(
                f"/api/conversations/{test_conversation.id}/chat/batch",
                headers=auth_headers,
                json={"message": "yes"},
            )

        stored = test_database.get_proposal(card.id, card.user_id)
        assert stored is not None and stored.state == "pending"


class TestDecline:
    def test_decline_answers_the_card_and_logs_time_to_decide(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        card = _card(test_database, test_conversation)

        with caplog.at_level(logging.INFO):
            response = client.post(f"/api/proposals/{card.id}/decline", headers=auth_headers)

        assert response.status_code == 200
        assert response.get_json()["state"] == "declined"
        record = next(r for r in caplog.records if r.getMessage() == "Deep research declined")
        assert record.decision_seconds >= 0
        assert record.sub_questions == 2
