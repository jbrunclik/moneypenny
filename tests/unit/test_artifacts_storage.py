"""Artifact storage and its cleanup triggers (src/db/models/artifacts.py)."""

from typing import Any

from src.api.schemas.common import MessageRole


def test_create_then_add_version(test_database: Any, test_conversation: Any) -> None:
    art, v1 = test_database.create_artifact(
        test_conversation.id, test_conversation.user_id, "Tip calculator", "<p>1</p>"
    )
    assert (v1.version, art.latest_version) == (1, 1)
    v2 = test_database.add_artifact_version(art.id, "<p>2</p>", title="Tips")
    assert v2.version == 2
    stored = test_database.get_artifact(art.id)
    assert stored is not None and (stored.latest_version, stored.title) == (2, "Tips")
    assert test_database.get_artifact_version(art.id, 1).html == "<p>1</p>"


def test_count_per_conversation(test_database: Any, test_conversation: Any) -> None:
    assert test_database.count_conversation_artifacts(test_conversation.id) == 0
    test_database.create_artifact(test_conversation.id, test_conversation.user_id, "A", "a")
    test_database.create_artifact(test_conversation.id, test_conversation.user_id, "B", "b")
    assert test_database.count_conversation_artifacts(test_conversation.id) == 2


def test_state_round_trip(test_database: Any, test_conversation: Any) -> None:
    art, _ = test_database.create_artifact(
        test_conversation.id, test_conversation.user_id, "T", "x"
    )
    test_database.set_artifact_state(art.id, {"checked": [1, 3]})
    assert test_database.get_artifact(art.id).state == {"checked": [1, 3]}
    test_database.set_artifact_state(art.id, None)
    assert test_database.get_artifact(art.id).state is None


def test_ownership_lookup(test_database: Any, test_conversation: Any) -> None:
    art, _ = test_database.create_artifact(
        test_conversation.id, test_conversation.user_id, "T", "x"
    )
    assert test_database.get_artifact_for_user(art.id, test_conversation.user_id) is not None
    assert test_database.get_artifact_for_user(art.id, "someone-else") is None


def test_deleting_the_message_removes_its_versions(
    test_database: Any, test_conversation: Any
) -> None:
    conv_id, user_id = test_conversation.id, test_conversation.user_id
    art, _ = test_database.create_artifact(conv_id, user_id, "T", "v1")
    m1 = test_database.add_message(conv_id, MessageRole.ASSISTANT, "made it")
    test_database.link_artifact_versions(m1.id, [(art.id, 1)])
    test_database.add_artifact_version(art.id, "v2")
    m2 = test_database.add_message(conv_id, MessageRole.ASSISTANT, "revised")
    test_database.link_artifact_versions(m2.id, [(art.id, 2)])

    test_database.delete_messages_after(conv_id, user_id, m2.id, inclusive=True)

    assert test_database.get_artifact_version(art.id, 2) is None
    assert test_database.get_artifact(art.id).latest_version == 1

    test_database.delete_messages_after(conv_id, user_id, m1.id, inclusive=True)
    assert test_database.get_artifact(art.id) is None


def test_deleting_the_conversation_removes_its_artifacts(
    test_database: Any, test_conversation: Any
) -> None:
    art, _ = test_database.create_artifact(
        test_conversation.id, test_conversation.user_id, "T", "x"
    )
    test_database.delete_conversation(test_conversation.id, test_conversation.user_id)
    assert test_database.get_artifact(art.id) is None
    assert test_database.get_artifact_version(art.id, 1) is None
