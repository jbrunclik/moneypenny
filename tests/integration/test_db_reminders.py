"""Reminders: one-off pushes the scheduler sends at their time, exactly once."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.models import Database, User

_NOW = datetime(2026, 11, 13, 7, 0, tzinfo=UTC)


def test_reminders_list_in_due_order(test_database: Database, test_user: User) -> None:
    later = test_database.add_reminder(test_user.id, None, "Later", _NOW + timedelta(hours=2))
    sooner = test_database.add_reminder(test_user.id, "conv-1", "Sooner", _NOW + timedelta(hours=1))

    listed = test_database.list_reminders(test_user.id)

    assert [r.id for r in listed] == [sooner.id, later.id]
    assert listed[0].conversation_id == "conv-1"
    assert listed[0].due_at == _NOW + timedelta(hours=1)
    assert listed[0].status == "pending"


def test_cancel_only_own_pending_reminders(test_database: Database, test_user: User) -> None:
    reminder = test_database.add_reminder(test_user.id, None, "Call the plumber", _NOW)

    assert test_database.cancel_reminder(reminder.id, "someone-else") is False
    assert test_database.cancel_reminder(reminder.id, test_user.id) is True
    assert test_database.cancel_reminder(reminder.id, test_user.id) is False
    assert test_database.list_reminders(test_user.id) == []


def test_claim_due_reminders_returns_each_once(test_database: Database, test_user: User) -> None:
    due = test_database.add_reminder(test_user.id, None, "Due", _NOW - timedelta(minutes=1))
    test_database.add_reminder(test_user.id, None, "Future", _NOW + timedelta(minutes=5))
    cancelled = test_database.add_reminder(
        test_user.id, None, "Cancelled", _NOW - timedelta(minutes=2)
    )
    test_database.cancel_reminder(cancelled.id, test_user.id)

    first = test_database.claim_due_reminders(_NOW)
    second = test_database.claim_due_reminders(_NOW)

    assert [r.id for r in first] == [due.id]
    assert first[0].status == "sent"
    assert second == []
    assert [r.text for r in test_database.list_reminders(test_user.id)] == ["Future"]
