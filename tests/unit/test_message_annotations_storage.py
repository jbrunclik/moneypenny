"""Annotations and the grounding summary round-trip through the messages table."""

from typing import TYPE_CHECKING

from src.api.schemas.common import MessageRole
from src.api.utils import serialize_messages_for_response

if TYPE_CHECKING:
    from src.db.models import Conversation, Database

_ANNS = [
    {
        "type": "claim",
        "verdict": "not_found",
        "quote": "PřepiServis",
        "prefix": "",
        "reason": "Není.",
    }
]
_SUMMARY = {"checked": True, "source_count": 3}


def test_add_and_read_back(test_database: Database, test_conversation: Conversation) -> None:
    msg = test_database.add_message(
        test_conversation.id, MessageRole.ASSISTANT, "text", annotations=_ANNS, grounding=_SUMMARY
    )

    [stored] = [m for m in test_database.get_messages(test_conversation.id) if m.id == msg.id]
    assert stored.annotations == _ANNS
    assert stored.grounding == _SUMMARY
    assert stored.content == "text"


def test_update_message_content_sets_them(
    test_database: Database, test_conversation: Conversation
) -> None:
    msg = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "")

    updated = test_database.update_message_content(
        msg.id, "final", annotations=_ANNS, grounding=_SUMMARY
    )

    assert updated is not None
    assert updated.annotations == _ANNS
    assert updated.grounding == _SUMMARY


def test_serializer_includes_them_only_when_present(
    test_database: Database, test_conversation: Conversation
) -> None:
    with_anns = test_database.add_message(
        test_conversation.id, MessageRole.ASSISTANT, "a", annotations=_ANNS, grounding=_SUMMARY
    )
    plain = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "b")

    out = {m["id"]: m for m in serialize_messages_for_response([with_anns, plain])}

    assert out[with_anns.id]["annotations"] == _ANNS
    assert out[with_anns.id]["grounding"] == _SUMMARY
    assert "annotations" not in out[plain.id]
    assert "grounding" not in out[plain.id]
