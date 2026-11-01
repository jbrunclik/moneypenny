"""Conversation facts storage: settled facts per conversation, each following
the reply that last set it (docs/features/conversation-facts.md)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.models import Database, User


def _conv_with_replies(db: Database, user: User, replies: int) -> tuple[str, list[str]]:
    conv = db.create_conversation(user.id)
    ids = []
    for n in range(replies):
        db.add_message(conv.id, "user", f"q{n}")
        ids.append(db.add_message(conv.id, "assistant", f"a{n}").id)
    return conv.id, ids


def _facts(db: Database, conv_id: str) -> list[tuple[str, str, str]]:
    return [(f.key, f.text, f.message_id) for f in db.get_conversation_facts(conv_id)]


def test_set_replace_and_remove(test_database: Database, test_user: User) -> None:
    conv_id, (a, b) = _conv_with_replies(test_database, test_user, 2)
    walls = "All partitions are reinforced concrete except one brick wall"

    test_database.apply_conversation_facts(conv_id, test_user.id, a, [("walls", walls)], [])
    assert _facts(test_database, conv_id) == [("walls", walls, a)]

    test_database.apply_conversation_facts(
        conv_id, test_user.id, b, [("walls", walls + " in room 2141.5")], []
    )
    assert _facts(test_database, conv_id) == [("walls", walls + " in room 2141.5", b)]

    test_database.apply_conversation_facts(conv_id, test_user.id, b, [], ["walls"])
    assert _facts(test_database, conv_id) == []


def test_deleting_the_setting_message_drops_its_facts(
    test_database: Database, test_user: User
) -> None:
    conv_id, (a, b) = _conv_with_replies(test_database, test_user, 2)
    test_database.apply_conversation_facts(conv_id, test_user.id, a, [("blinds", "Installed")], [])
    test_database.apply_conversation_facts(conv_id, test_user.id, b, [("walls", "Concrete")], [])

    test_database.delete_message_by_id(a)

    assert _facts(test_database, conv_id) == [("walls", "Concrete", b)]


def test_deleting_the_conversation_drops_its_facts(
    test_database: Database, test_user: User
) -> None:
    conv_id, (a,) = _conv_with_replies(test_database, test_user, 1)
    test_database.apply_conversation_facts(conv_id, test_user.id, a, [("walls", "Concrete")], [])

    test_database.delete_conversation(conv_id, test_user.id)

    assert test_database.get_conversation_facts(conv_id) == []


def test_cap_rejects_past_the_count_and_long_facts(
    test_database: Database, test_user: User
) -> None:
    conv_id, (a,) = _conv_with_replies(test_database, test_user, 1)
    full = [(f"fact-{n}", f"Fact {n}") for n in range(30)]
    assert test_database.apply_conversation_facts(conv_id, test_user.id, a, full, []).applied == 30

    over = test_database.apply_conversation_facts(conv_id, test_user.id, a, [("new", "x")], [])
    assert (over.applied, over.rejected) == (0, 1)
    replaced = test_database.apply_conversation_facts(
        conv_id, test_user.id, a, [("fact-0", "Changed")], []
    )
    assert replaced.applied == 1
    long = test_database.apply_conversation_facts(
        conv_id, test_user.id, a, [("fact-1", "y" * 201)], []
    )
    assert long.rejected == 1
    assert len(test_database.get_conversation_facts(conv_id)) == 30


def test_keys_are_normalized(test_database: Database, test_user: User) -> None:
    conv_id, (a,) = _conv_with_replies(test_database, test_user, 1)
    test_database.apply_conversation_facts(
        conv_id, test_user.id, a, [(" Partition Walls ", "Concrete")], []
    )
    test_database.apply_conversation_facts(conv_id, test_user.id, a, [], ["partition walls"])
    assert test_database.get_conversation_facts(conv_id) == []
    test_database.apply_conversation_facts(conv_id, test_user.id, a, [("A" * 60, "Long key")], [])
    assert _facts(test_database, conv_id)[0][0] == "a" * 40
