"""The every-minute scheduler drives scheduled items through their lifecycle
(src/agent/item_scheduler.py): fire, run, back off, catch missed ones,
expire, stop after failures. The model run and the push sender are faked."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from src.agent import item_scheduler
from src.agent.item_runner import RunOutcome
from src.config import Config
from src.db.models import use_database
from src.db.models.dataclasses import ScheduledItem

if TYPE_CHECKING:
    from src.db.models import Conversation, Database, User

_NOW = datetime(2026, 11, 13, 17, 0, tzinfo=UTC)  # Fri 18:00 in Prague


@pytest.fixture
def db(test_database: Database, monkeypatch: pytest.MonkeyPatch) -> Generator[Database]:
    monkeypatch.setattr(Config, "APP_TIMEZONE", "Europe/Prague")
    with use_database(test_database):
        yield test_database


@pytest.fixture
def push() -> Generator[MagicMock]:
    sent = MagicMock()
    with (
        patch("src.agent.item_runner.send_push_to_user", sent),
        patch("src.agent.item_scheduler.send_push_to_user", sent),
    ):
        yield sent


@pytest.fixture
def runs() -> Generator[MagicMock]:
    with patch("src.agent.item_scheduler.run_model_item") as run:
        run.return_value = RunOutcome("silent", "")
        yield run


def _add(
    db: Database, user: User, conversation: Conversation, **overrides: object
) -> ScheduledItem:
    item = ScheduledItem(
        id=str(uuid.uuid4()),
        user_id=user.id,
        conversation_id=conversation.id,
        kind="reminder",
        text="Call the plumber",
        end_condition=None,
        schedule=None,
        interval_hours=None,
        next_run_at=_NOW,
        expires_at=None,
        status="active",
        last_result=None,
        quiet_runs=0,
        failures=0,
        created_at=_NOW - timedelta(days=1),
    )
    return db.add_item(replace(item, **overrides))  # type: ignore[arg-type]


def _watcher(
    db: Database, user: User, conversation: Conversation, **overrides: object
) -> ScheduledItem:
    fields: dict[str, object] = {
        "kind": "watcher",
        "text": "the school's job board",
        "end_condition": "a teacher job is posted",
        "interval_hours": 24,
    }
    return _add(db, user, conversation, **(fields | overrides))


def _deliveries(db: Database, conversation: Conversation) -> list[tuple[str, str | None]]:
    return [
        (m.content, m.delivery["label"] if m.delivery else None)
        for m in db.get_messages(conversation.id)
    ]


def test_reminder_pushes_and_is_deleted(
    db: Database, test_user: User, test_conversation: Conversation, push: MagicMock, runs: MagicMock
) -> None:
    _add(db, test_user, test_conversation)

    result = item_scheduler.run_due_items(_NOW)

    assert result.fired == 1
    push.assert_called_once()
    assert push.call_args.args[2] == "Call the plumber"
    assert db.get_messages(test_conversation.id) == []
    assert db.list_items(test_user.id) == []


def test_check_in_posts_a_labelled_turn_pushes_and_is_deleted(
    db: Database, test_user: User, test_conversation: Conversation, push: MagicMock, runs: MagicMock
) -> None:
    _add(db, test_user, test_conversation, kind="check_in", text="How's the tail?")

    item_scheduler.run_due_items(_NOW)

    assert _deliveries(db, test_conversation) == [("How's the tail?", "Check-in · Fri 18:00")]
    push.assert_called_once()
    assert db.list_items(test_user.id) == []


def test_late_within_grace_fires(
    db: Database, test_user: User, test_conversation: Conversation, push: MagicMock, runs: MagicMock
) -> None:
    _add(db, test_user, test_conversation, next_run_at=_NOW - timedelta(hours=3))

    result = item_scheduler.run_due_items(_NOW)

    assert (result.fired, result.missed) == (1, 0)
    push.assert_called_once()


def test_late_past_grace_is_missed(
    db: Database, test_user: User, test_conversation: Conversation, push: MagicMock, runs: MagicMock
) -> None:
    _add(db, test_user, test_conversation, next_run_at=_NOW - timedelta(hours=7))

    result = item_scheduler.run_due_items(_NOW)

    assert (result.fired, result.missed) == (0, 1)
    [(text, label)] = _deliveries(db, test_conversation)
    assert text == "Missed (was due Fri 13 Nov 2026 11:00): Call the plumber"
    assert label == "Reminder · missed"
    push.assert_not_called()
    assert db.list_items(test_user.id) == []


def test_watcher_silent_backs_off(
    db: Database, test_user: User, test_conversation: Conversation, push: MagicMock, runs: MagicMock
) -> None:
    item = _watcher(db, test_user, test_conversation, quiet_runs=6)

    item_scheduler.run_due_items(_NOW)

    stored = db.get_item(item.id, test_user.id)
    assert stored is not None
    assert (stored.quiet_runs, stored.next_run_at) == (7, _NOW + timedelta(hours=48))
    assert db.get_messages(test_conversation.id) == []
    push.assert_not_called()


def test_a_watcher_with_an_end_date_does_not_back_off(
    db: Database, test_user: User, test_conversation: Conversation, push: MagicMock, runs: MagicMock
) -> None:
    item = _watcher(
        db, test_user, test_conversation, quiet_runs=6, expires_at=_NOW + timedelta(days=10)
    )

    item_scheduler.run_due_items(_NOW)

    stored = db.get_item(item.id, test_user.id)
    assert stored is not None
    assert stored.next_run_at == _NOW + timedelta(hours=24)


def test_back_off_is_capped_at_weekly() -> None:
    assert item_scheduler.next_watch_run(_NOW, 24, 70, has_until=False) == _NOW + timedelta(
        hours=168
    )
    assert item_scheduler.next_watch_run(_NOW, 6, 7, has_until=False) == _NOW + timedelta(hours=12)


def test_watcher_report_delivers_and_resets_quiet_runs(
    db: Database, test_user: User, test_conversation: Conversation, push: MagicMock, runs: MagicMock
) -> None:
    item = _watcher(db, test_user, test_conversation, quiet_runs=5)
    runs.return_value = RunOutcome("report", "A caretaker job was posted.")

    item_scheduler.run_due_items(_NOW)

    assert _deliveries(db, test_conversation) == [
        ("A caretaker job was posted.", "Watcher · update")
    ]
    stored = db.get_item(item.id, test_user.id)
    assert stored is not None
    assert (stored.quiet_runs, stored.last_result) == (0, "A caretaker job was posted.")
    push.assert_called_once()


def test_watcher_done_delivers_and_is_deleted(
    db: Database, test_user: User, test_conversation: Conversation, push: MagicMock, runs: MagicMock
) -> None:
    _watcher(db, test_user, test_conversation)
    runs.return_value = RunOutcome("done", "A teacher job is posted.")

    item_scheduler.run_due_items(_NOW)

    assert _deliveries(db, test_conversation) == [("A teacher job is posted.", "Watcher · found")]
    assert db.list_items(test_user.id) == []


def test_watcher_expired_posts_stopped_turn_without_push(
    db: Database, test_user: User, test_conversation: Conversation, push: MagicMock, runs: MagicMock
) -> None:
    _watcher(db, test_user, test_conversation, created_at=_NOW - timedelta(days=31))

    result = item_scheduler.run_due_items(_NOW)

    assert result.expired == 1
    [(text, label)] = _deliveries(db, test_conversation)
    assert text.startswith("Stopped watching: the school's job board")
    assert label == "Watcher · stopped"
    runs.assert_not_called()
    push.assert_not_called()
    assert db.list_items(test_user.id) == []


def test_three_failures_stop_the_watcher(
    db: Database, test_user: User, test_conversation: Conversation, push: MagicMock, runs: MagicMock
) -> None:
    item = _watcher(db, test_user, test_conversation, failures=1)
    runs.return_value = RunOutcome("failed", "", error="llm down")

    item_scheduler.run_due_items(_NOW)
    stored = db.get_item(item.id, test_user.id)
    assert stored is not None and stored.failures == 2

    item_scheduler.run_due_items(stored.next_run_at)

    [(text, label)] = _deliveries(db, test_conversation)
    assert text.startswith("Stopped watching - kept failing")
    assert label == "Watcher · stopped"
    assert db.list_items(test_user.id) == []


def test_a_success_resets_the_failures(
    db: Database, test_user: User, test_conversation: Conversation, push: MagicMock, runs: MagicMock
) -> None:
    item = _watcher(db, test_user, test_conversation, failures=2)

    item_scheduler.run_due_items(_NOW)

    stored = db.get_item(item.id, test_user.id)
    assert stored is not None and stored.failures == 0


def test_recurring_runs_on_its_cron_and_stays(
    db: Database, test_user: User, test_conversation: Conversation, push: MagicMock, runs: MagicMock
) -> None:
    item = _add(
        db, test_user, test_conversation, kind="recurring", schedule="0 9 * * 1", text="School menu"
    )
    runs.return_value = RunOutcome("report", "Monday: soup and schnitzel.")

    item_scheduler.run_due_items(_NOW)

    stored = db.get_item(item.id, test_user.id)
    assert stored is not None
    assert stored.next_run_at == datetime(2026, 11, 16, 8, 0, tzinfo=UTC)  # Mon 09:00 Prague
    assert _deliveries(db, test_conversation) == [
        ("Monday: soup and schnitzel.", "Recurring · Fri 18:00")
    ]


def test_recurring_until_date_expires_quietly(
    db: Database, test_user: User, test_conversation: Conversation, push: MagicMock, runs: MagicMock
) -> None:
    _add(
        db,
        test_user,
        test_conversation,
        kind="recurring",
        schedule="0 9 * * 1",
        text="School menu",
        expires_at=_NOW - timedelta(minutes=1),
    )

    item_scheduler.run_due_items(_NOW)

    [(text, label)] = _deliveries(db, test_conversation)
    assert text == "Stopped: reached its end date - School menu"
    assert label == "Recurring · stopped"
    push.assert_not_called()
    assert db.list_items(test_user.id) == []


def test_the_next_run_never_passes_the_expiry(
    db: Database, test_user: User, test_conversation: Conversation, push: MagicMock, runs: MagicMock
) -> None:
    expiry = _NOW + timedelta(hours=5)
    item = _watcher(db, test_user, test_conversation, interval_hours=168, expires_at=expiry)

    item_scheduler.run_due_items(_NOW)

    stored = db.get_item(item.id, test_user.id)
    assert stored is not None and stored.next_run_at == expiry


def test_resume_runs_once(
    db: Database, test_user: User, test_conversation: Conversation, push: MagicMock, runs: MagicMock
) -> None:
    item = _watcher(db, test_user, test_conversation, next_run_at=_NOW - timedelta(days=14))

    item_scheduler.run_due_items(_NOW)
    item_scheduler.run_due_items(_NOW + timedelta(minutes=1))

    assert runs.call_count == 1
    stored = db.get_item(item.id, test_user.id)
    assert stored is not None and stored.next_run_at == _NOW + timedelta(hours=24)


def test_stale_runs_are_reset_each_tick(
    db: Database, test_user: User, test_conversation: Conversation, push: MagicMock, runs: MagicMock
) -> None:
    _watcher(db, test_user, test_conversation)
    db.claim_due_items(_NOW - timedelta(hours=1))  # a crashed run left it "running"

    result = item_scheduler.run_due_items(_NOW)

    assert result.run == 1


def test_one_bad_item_does_not_stop_the_tick(
    db: Database, test_user: User, test_conversation: Conversation, push: MagicMock, runs: MagicMock
) -> None:
    _watcher(db, test_user, test_conversation)
    _add(db, test_user, test_conversation, text="Second")
    runs.side_effect = RuntimeError("boom")

    result = item_scheduler.run_due_items(_NOW)

    assert result.fired == 1
