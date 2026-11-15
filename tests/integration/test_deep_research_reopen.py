"""Re-opening a started deep-research card: a run a deploy killed, or a
Regenerate / Continue / Retry on the run's turn, puts the card back on the
table (no autostart, the plan editable) instead of an ordinary turn on
"Start deep research"."""

from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from flask.testing import FlaskClient

from src.enums import MessageRole
from tests.integration.test_deep_research_start import _card, _start, _stream

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, Proposal


def _started(
    client: FlaskClient, headers: dict[str, str], conv: Conversation, db: Database
) -> tuple[Proposal, str]:
    """A card started with an edited plan; the Start message's id."""
    card = _card(db, conv)
    response = _stream(client, headers, conv.id, _start(card.id, ["a", "c"], "Brno"))
    assert response.status_code == 200
    start = next(
        m for m in db.get_messages(conv.id) if m.role == MessageRole.USER and m.action is not None
    )
    return card, start.id


def _reopen(client: FlaskClient, headers: dict[str, str], card_id: str, message_id: str) -> Any:
    return client.post(
        f"/api/proposals/{card_id}/reopen", headers=headers, json={"message_id": message_id}
    )


class TestReopen:
    def test_reopens_the_card_with_the_started_plan_and_drops_the_run(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        card, start_id = _started(client, auth_headers, test_conversation, test_database)

        response = _reopen(client, auth_headers, card.id, start_id)

        assert response.status_code == 200
        body = response.get_json()
        assert body["state"] == "pending"
        # The editor shows what was started, and nothing counts down
        assert body["research"]["sub_questions"] == ["a", "c"]
        assert body["research"]["context"] == "Brno"
        assert body["research"]["autostart"] is False
        stored = test_database.get_proposal(card.id, card.user_id)
        assert stored is not None
        assert (stored.state, stored.chosen, stored.resolved_by) == ("pending", None, None)
        assert stored.options[0]["payload"]["status"] == "offered"
        # The Start message and the run after it are gone; the offer reply stays
        remaining = test_database.get_messages(test_conversation.id)
        assert [m.id for m in remaining] == [card.message_id]

    def test_the_reopened_card_starts_again(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        card, start_id = _started(client, auth_headers, test_conversation, test_database)
        assert _reopen(client, auth_headers, card.id, start_id).status_code == 200

        response = _stream(client, auth_headers, test_conversation.id, _start(card.id, ["a"]))

        assert response.status_code == 200
        response.research_ran.assert_called_once()

    def test_refused_while_a_turn_runs(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        card, start_id = _started(client, auth_headers, test_conversation, test_database)

        with patch("src.api.routes.proposals.running_turn_id", return_value="reply-1"):
            response = _reopen(client, auth_headers, card.id, start_id)

        assert response.status_code == 409
        stored = test_database.get_proposal(card.id, card.user_id)
        assert stored is not None and stored.state == "approved"
        assert len(test_database.get_messages(test_conversation.id)) > 1

    def test_refused_for_a_message_that_did_not_start_this_card(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        card, _ = _started(client, auth_headers, test_conversation, test_database)
        plain = test_database.add_message(test_conversation.id, MessageRole.USER, "hi")

        response = _reopen(client, auth_headers, card.id, plain.id)

        assert response.status_code == 409
        assert test_database.get_message_by_id(plain.id) is not None

    def test_refused_for_a_card_that_never_started(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        card = _card(test_database, test_conversation, state="declined")
        user = test_database.add_message(test_conversation.id, MessageRole.USER, "x")

        assert _reopen(client, auth_headers, card.id, user.id).status_code == 409

    def test_an_offer_made_after_the_start_closes(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        card, start_id = _started(client, auth_headers, test_conversation, test_database)
        newer = _card(test_database, test_conversation)

        assert _reopen(client, auth_headers, card.id, start_id).status_code == 200

        # Its reply came after the Start message, so it went with the run
        stored = test_database.get_proposal(newer.id, newer.user_id)
        assert stored is not None and stored.state != "pending"

    def test_another_users_card_is_not_found(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
        test_database: Database,
    ) -> None:
        response = _reopen(client, auth_headers, "no-such-card", "no-such-message")

        assert response.status_code == 404
