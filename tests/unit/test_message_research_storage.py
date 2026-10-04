"""Deep-research offer / run data round-trips through messages.research."""

from typing import TYPE_CHECKING, Any

import pytest

from src.api.schemas.common import MessageRole
from src.api.utils import serialize_messages_for_response

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


def test_find_open_offers_matches_offers_and_followups(
    test_database: Database, test_conversation: Conversation
) -> None:
    db, conv = test_database, test_conversation.id
    open_offer = db.add_message(conv, MessageRole.ASSISTANT, "a", research=_OFFER)
    db.add_message(conv, MessageRole.ASSISTANT, "b", research={"offer": {"status": "declined"}})
    followup = db.add_message(
        conv, MessageRole.ASSISTANT, "c", research={"run": {"followup": {"status": "offered"}}}
    )
    db.add_message(conv, MessageRole.ASSISTANT, "d")

    found = {m.id for m in db.find_open_research_offers(conv)}

    assert found == {open_offer.id, followup.id}


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


def test_a_decision_lands_only_while_the_offer_is_open(
    test_database: Any, test_conversation: Any
) -> None:
    """Two devices starting one offer at once: only the first may win."""
    offered = {"offer": {"status": "offered"}}
    msg_id = test_database.add_message(
        test_conversation.id, MessageRole.ASSISTANT, "x", research=offered
    ).id
    started = {"offer": {"status": "started"}}

    assert test_database.decide_research_offer(msg_id, "$.offer.status", started) is True
    assert test_database.decide_research_offer(msg_id, "$.offer.status", started) is False
    assert test_database.get_message_by_id(msg_id).research == started


def test_starting_a_stale_offer_conflicts(
    test_database: Any, test_conversation: Any, monkeypatch: Any
) -> None:
    """start_plan reads the offer, then writes: a start that landed in between wins."""
    from src.agent.deep_research import plan as plan_mod
    from src.agent.deep_research.offer import build_offer

    monkeypatch.setattr(plan_mod, "db", test_database)
    offer_id = test_database.add_message(
        test_conversation.id,
        MessageRole.ASSISTANT,
        "x",
        research={"offer": build_offer({"question": "Q", "context": "", "sub_questions": ["a"]})},
    ).id
    stale = test_database.get_message_by_id(offer_id)
    plan_mod.start_plan(test_conversation.id, offer_id, ["a"], "")  # the other device
    monkeypatch.setattr(test_database, "get_message_by_id", lambda _id: stale)

    with pytest.raises(plan_mod.OfferConflict):
        plan_mod.start_plan(test_conversation.id, offer_id, ["a"], "")
