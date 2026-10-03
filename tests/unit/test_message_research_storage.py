"""Deep-research offer / run data round-trips through messages.research."""

from typing import TYPE_CHECKING

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
