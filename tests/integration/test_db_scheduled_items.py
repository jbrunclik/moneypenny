"""Scheduled items set from chat: they follow their chat, and the scheduler
claims each due one exactly once."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from src.db.models.dataclasses import ScheduledItem
from src.enums import MessageRole

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, User

_NOW = datetime(2026, 11, 13, 7, 0, tzinfo=UTC)


def _item(user: User, conversation: Conversation, **overrides: object) -> ScheduledItem:
    item = ScheduledItem(
        id=str(uuid.uuid4()),
        user_id=user.id,
        conversation_id=conversation.id,
        kind="reminder",
        text="Call the plumber",
        end_condition=None,
        schedule=None,
        interval_hours=None,
        next_run_at=_NOW - timedelta(minutes=1),
        expires_at=None,
        status="active",
        last_result=None,
        quiet_runs=0,
        failures=0,
        created_at=_NOW - timedelta(days=1),
        claimed_at=None,
    )
    return replace(item, **overrides)  # type: ignore[arg-type]


def _count(database: Database) -> int:
    with database._pool.get_connection() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM scheduled_items").fetchone()[0])


def test_add_and_list_soonest_first(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    later = test_database.add_item(
        _item(test_user, test_conversation, next_run_at=_NOW + timedelta(hours=2))
    )
    sooner = test_database.add_item(
        _item(test_user, test_conversation, next_run_at=_NOW + timedelta(hours=1))
    )

    listed = test_database.list_items(test_user.id)

    assert [i.id for i in listed] == [sooner.id, later.id]
    assert listed[0] == sooner
    assert test_database.list_items(test_user.id, conversation_id="other") == []
    assert test_database.count_items(test_user.id) == 2


def test_items_follow_their_chat(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    item = test_database.add_item(_item(test_user, test_conversation))

    test_database.trash_conversation(test_conversation.id, test_user.id)
    assert test_database.list_items(test_user.id) == []
    assert test_database.claim_due_items(_NOW) == []
    test_database.restore_conversation(test_conversation.id, test_user.id)
    assert [i.id for i in test_database.list_items(test_user.id)] == [item.id]

    test_database.archive_conversation(test_conversation.id, test_user.id)
    assert test_database.count_items(test_user.id) == 0
    assert test_database.claim_due_items(_NOW) == []
    test_database.unarchive_conversation(test_conversation.id, test_user.id)
    assert [i.id for i in test_database.claim_due_items(_NOW)] == [item.id]


def test_delete_conversation_deletes_items(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    test_database.add_item(_item(test_user, test_conversation))

    test_database.delete_conversation(test_conversation.id, test_user.id)

    assert _count(test_database) == 0


def test_emptying_the_trash_deletes_items(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    test_database.add_item(_item(test_user, test_conversation))
    test_database.trash_conversation(test_conversation.id, test_user.id)

    test_database.empty_trash(test_user.id)

    assert _count(test_database) == 0


def test_claim_marks_running_once(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    due = test_database.add_item(_item(test_user, test_conversation, kind="watcher"))
    test_database.add_item(_item(test_user, test_conversation, next_run_at=_NOW + timedelta(1)))

    first = test_database.claim_due_items(_NOW)
    second = test_database.claim_due_items(_NOW)

    assert [i.id for i in first] == [due.id]
    assert first[0].status == "running"
    assert first[0].claimed_at == _NOW
    assert second == []


def test_paused_is_not_claimed(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    item = test_database.add_item(_item(test_user, test_conversation, kind="watcher"))

    assert test_database.set_item_paused(item.id, test_user.id, paused=True) is True

    assert test_database.claim_due_items(_NOW) == []
    assert test_database.set_item_paused(item.id, test_user.id, paused=False) is True
    assert len(test_database.claim_due_items(_NOW)) == 1


def test_stale_running_is_reset(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    test_database.add_item(_item(test_user, test_conversation, kind="watcher"))
    test_database.claim_due_items(_NOW)

    assert test_database.reset_stale_runs(_NOW + timedelta(minutes=5), 30) == 0
    assert test_database.reset_stale_runs(_NOW + timedelta(minutes=31), 30) == 1
    assert len(test_database.claim_due_items(_NOW + timedelta(minutes=31))) == 1


def test_finish_item_run_sets_next_and_state(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    item = test_database.add_item(_item(test_user, test_conversation, kind="watcher"))
    test_database.claim_due_items(_NOW)
    next_run = _NOW + timedelta(days=1)

    test_database.finish_item_run(item.id, next_run, "No job yet", quiet_runs=2, failures=1)

    stored = test_database.get_item(item.id, test_user.id)
    assert stored is not None
    assert (stored.status, stored.next_run_at, stored.last_result) == (
        "active",
        next_run,
        "No job yet",
    )
    assert (stored.quiet_runs, stored.failures, stored.claimed_at) == (2, 1, None)


def test_scoped_to_user(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    item = test_database.add_item(_item(test_user, test_conversation, kind="watcher"))

    assert test_database.get_item(item.id, "someone-else") is None
    assert test_database.set_item_paused(item.id, "someone-else", paused=True) is False
    assert test_database.delete_item(item.id, "someone-else") is False
    assert test_database.delete_item(item.id, test_user.id) is True
    assert test_database.delete_item(item.id) is False


def test_message_delivery_round_trips(
    test_database: Database, test_conversation: Conversation
) -> None:
    label = {"kind": "check_in", "label": "Check-in · Fri 18:00"}
    test_database.add_message(
        test_conversation.id,
        MessageRole.ASSISTANT,
        "How's the tail?",
        delivery=label,  # type: ignore[arg-type]
    )
    test_database.add_message(test_conversation.id, MessageRole.USER, "Better")

    messages = test_database.get_messages(test_conversation.id)

    assert [m.delivery for m in messages] == [label, None]
