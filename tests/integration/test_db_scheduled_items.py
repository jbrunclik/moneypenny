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


def test_a_stale_reset_counts_a_failure(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    # A run killed mid-way (scheduler timeout) must not re-run forever unbilled
    item = test_database.add_item(_item(test_user, test_conversation, kind="watcher", failures=1))
    test_database.claim_due_items(_NOW)

    test_database.reset_stale_runs(_NOW + timedelta(minutes=31), 30)

    stored = test_database.get_item(item.id, test_user.id)
    assert stored is not None and stored.failures == 2


def test_finishing_a_superseded_run_changes_nothing(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    item = test_database.add_item(_item(test_user, test_conversation, kind="watcher"))
    [first] = test_database.claim_due_items(_NOW)
    test_database.reset_stale_runs(_NOW + timedelta(minutes=31), 30)
    [second] = test_database.claim_due_items(_NOW + timedelta(minutes=31))

    finished = test_database.finish_item_run(
        item.id, _NOW + timedelta(days=1), "old run", 0, 0, claimed_at=first.claimed_at
    )

    assert finished is False
    stored = test_database.get_item(item.id, test_user.id)
    assert stored is not None
    assert (stored.status, stored.claimed_at, stored.last_result) == (
        "running",
        second.claimed_at,
        None,
    )


# Standing jobs (docs/superpowers/plans/2026-11-08-standing-chats-phase-2.md, A1)


def test_standing_fields_round_trip(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    job = test_database.add_item(
        _item(
            test_user,
            test_conversation,
            kind="recurring",
            schedule="15 7 * * *",
            grants=["garmin_connect", "todoist"],
            model="gemini-4-hydrogen",
            budget_usd=0.5,
            fresh_context=False,
            timezone="Europe/Prague",
        )
    )

    stored = test_database.get_item(job.id, test_user.id)

    assert stored == job
    assert stored is not None and stored.standing
    assert not _item(test_user, test_conversation).standing


def test_standing_jobs_do_not_count_toward_the_cap(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    test_database.add_item(_item(test_user, test_conversation))
    test_database.add_item(
        _item(test_user, test_conversation, kind="recurring", schedule="0 * * * *", grants=["*"])
    )

    assert test_database.count_items(test_user.id) == 1


def test_job_spend_today_counts_only_that_job(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    job = test_database.add_item(
        _item(test_user, test_conversation, kind="recurring", schedule="0 * * * *", grants=["*"])
    )
    run = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "report")
    turn = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "chat reply")
    common = (test_conversation.id, test_user.id, "m", 1, 1)
    test_database.save_message_cost(run.id, *common, 0.25, job_id=job.id)
    test_database.save_message_cost(turn.id, *common, 0.75)  # the user's own turn

    assert test_database.job_spend_today(job.id) == 0.25


def test_pause_reason_is_kept_and_cleared(
    test_database: Database, test_user: User, test_conversation: Conversation
) -> None:
    job = test_database.add_item(
        _item(test_user, test_conversation, kind="recurring", schedule="0 * * * *", grants=["*"])
    )

    assert test_database.set_item_paused(job.id, test_user.id, True, reason="failures")
    paused = test_database.get_item(job.id, test_user.id)
    assert paused is not None and paused.paused_reason == "failures"

    assert test_database.set_item_paused(job.id, test_user.id, False)
    resumed = test_database.get_item(job.id, test_user.id)
    assert resumed is not None and resumed.paused_reason is None


# Part B review: an agent's job is managed as the agent, never as a light item


def test_an_agents_job_is_not_listed_with_chat_items(
    test_database: Database, test_user: User
) -> None:
    agent = test_database.create_standing_chat(test_user.id, "VWCE Watcher", schedule="0 18 * * 5")

    assert test_database.list_items(test_user.id) == []
    assert test_database.list_items(test_user.id, agent.conversation_id) == []
    assert test_database.is_agent_job(agent.id)


def test_disabling_an_agent_mid_run_survives_the_run_ending(
    test_database: Database, test_user: User
) -> None:
    from src.db.models.scheduled_items import NEVER_RUN_AT

    agent = test_database.create_standing_chat(test_user.id, "Briefing", schedule="15 7 * * *")
    test_database.finish_item_run(agent.id, _NOW - timedelta(minutes=1), None, 0, 0)
    [claimed] = test_database.claim_due_items(_NOW)
    test_database.update_standing_chat(agent.id, test_user.id, enabled=False)

    test_database.finish_item_run(
        agent.id, _NOW + timedelta(days=1), None, 0, 0, claimed_at=claimed.claimed_at
    )

    job = test_database.get_item(agent.id, test_user.id)
    assert job is not None and (job.status, job.paused_reason) == ("paused", "disabled")
    assert test_database.claim_due_items(NEVER_RUN_AT) == []


def test_disabling_mid_hand_run_survives_the_release(
    test_database: Database, test_user: User
) -> None:
    agent = test_database.create_standing_chat(test_user.id, "Briefing", schedule="15 7 * * *")
    claim = test_database.claim_item(agent.id, _NOW)
    assert claim is not None
    test_database.update_standing_chat(agent.id, test_user.id, enabled=False)

    test_database.release_item(agent.id, claim[1], claim[0])

    job = test_database.get_item(agent.id, test_user.id)
    assert job is not None and job.status == "paused"


def test_renaming_an_agent_onto_another_name_is_refused(
    test_database: Database, test_user: User
) -> None:
    import sqlite3

    import pytest

    test_database.create_standing_chat(test_user.id, "Coach")
    other = test_database.create_standing_chat(test_user.id, "Watcher")

    with pytest.raises(sqlite3.IntegrityError):
        test_database.update_standing_chat(other.id, test_user.id, name="Coach")
