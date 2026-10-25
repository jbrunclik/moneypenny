"""Artifact refs round-trip through messages.artifacts and reach the API."""

from typing import TYPE_CHECKING

from src.api.utils import build_stream_done_event, serialize_messages_for_response
from src.enums import MessageRole

if TYPE_CHECKING:
    from src.db.models import Conversation, Database

_REFS = [{"id": "a1", "version": 2, "title": "Tips"}]


def test_add_and_update_round_trip(
    test_database: Database, test_conversation: Conversation
) -> None:
    msg = test_database.add_message(
        test_conversation.id, MessageRole.ASSISTANT, "x", artifacts=_REFS
    )
    [stored] = [m for m in test_database.get_messages(test_conversation.id) if m.id == msg.id]
    assert stored.artifacts == _REFS

    refs = [{"id": "a1", "version": 3, "title": "Tips"}]
    updated = test_database.update_message_content(msg.id, "y", artifacts=refs)
    assert updated is not None and updated.artifacts == refs


def test_serializer_includes_artifacts_only_when_set(
    test_database: Database, test_conversation: Conversation
) -> None:
    with_a = test_database.add_message(
        test_conversation.id, MessageRole.ASSISTANT, "a", artifacts=_REFS
    )
    plain = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "b")

    out = {m["id"]: m for m in serialize_messages_for_response([with_a, plain])}

    assert out[with_a.id]["artifacts"] == _REFS
    assert "artifacts" not in out[plain.id]


def test_done_event_carries_artifacts(
    test_database: Database, test_conversation: Conversation
) -> None:
    msg = test_database.add_message(
        test_conversation.id, MessageRole.ASSISTANT, "a", artifacts=_REFS
    )

    done = build_stream_done_event(msg, [], [], [])

    assert done["artifacts"] == _REFS
