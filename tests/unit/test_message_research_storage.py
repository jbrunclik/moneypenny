"""Deep-research offer / run data round-trips through messages.research."""

from typing import TYPE_CHECKING, Any

import pytest

from src.api.utils import serialize_messages_for_response
from src.db.models import use_database
from src.enums import MessageRole

if TYPE_CHECKING:
    from src.db.models import Conversation, Database

_OFFER = {"offer": {"question": "Q", "sub_questions": ["a"], "status": "offered"}}


def test_add_update_and_set(test_database: Database, test_conversation: Conversation) -> None:
    msg = test_database.add_message(
        test_conversation.id, MessageRole.ASSISTANT, "x", research=_OFFER
    )
    [stored] = [m for m in test_database.get_messages(test_conversation.id) if m.id == msg.id]
    assert stored.research == _OFFER

    updated = test_database.update_message_content(msg.id, "y", research={"run": {"round": 1}})
    assert updated is not None and updated.research == {"run": {"round": 1}}

    test_database.set_message_research(msg.id, {"offer": {"status": "declined"}})
    [stored] = [m for m in test_database.get_messages(test_conversation.id) if m.id == msg.id]
    assert stored.research == {"offer": {"status": "declined"}}


def test_serializer_includes_research_only_when_set(
    test_database: Database, test_conversation: Conversation
) -> None:
    with_r = test_database.add_message(
        test_conversation.id, MessageRole.ASSISTANT, "a", research=_OFFER
    )
    plain = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "b")

    out = {m["id"]: m for m in serialize_messages_for_response([with_r, plain])}

    assert out[with_r.id]["research"] == _OFFER
    assert "research" not in out[plain.id]


def test_starting_a_stale_card_conflicts(test_database: Any, test_conversation: Any) -> None:
    """Two devices starting one offer at once: the first start wins, the
    other conflicts (the claim is one atomic UPDATE)."""
    from src.agent.deep_research import plan as plan_mod
    from src.agent.deep_research.offer import build_offer, file_offer_card

    offer = build_offer({"question": "Q", "context": "", "sub_questions": ["a"]})
    user_id = test_conversation.user_id
    with use_database(test_database):
        card = file_offer_card(offer, test_conversation.id, user_id, request_id="t")
        reply = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "x")
        test_database.link_proposals("t", reply.id)
        plan_mod.start_plan(test_conversation.id, user_id, card.id, ["a"], "")  # the other device
        with pytest.raises(plan_mod.OfferConflictError):
            plan_mod.start_plan(test_conversation.id, user_id, card.id, ["a"], "")
