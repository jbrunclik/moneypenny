"""The every-minute scheduler pushes due reminders - once each, before agents run."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from src.agent import scheduler

if TYPE_CHECKING:
    from src.db.models import Database, User

_NOW = datetime(2026, 11, 13, 7, 0, tzinfo=UTC)


@pytest.fixture
def push(test_database: Database, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    sent = MagicMock()
    monkeypatch.setattr(scheduler, "db", test_database)
    monkeypatch.setattr(scheduler, "send_push_to_user", sent)
    return sent


def test_a_due_reminder_pushes_once_with_its_conversation(
    test_database: Database, test_user: User, push: MagicMock
) -> None:
    reminder = test_database.add_reminder(
        test_user.id, "conv-9", "Call the plumber", _NOW - timedelta(seconds=30)
    )

    assert scheduler.send_due_reminders(_NOW) == 1
    assert scheduler.send_due_reminders(_NOW) == 0

    push.assert_called_once_with(
        test_user.id,
        "Reminder",
        "Call the plumber",
        url="/#/conversations/conv-9",
        tag=f"reminder-{reminder.id}",
    )


def test_a_future_reminder_is_not_sent(
    test_database: Database, test_user: User, push: MagicMock
) -> None:
    test_database.add_reminder(test_user.id, None, "Later", _NOW + timedelta(minutes=1))

    assert scheduler.send_due_reminders(_NOW) == 0
    push.assert_not_called()


def test_a_push_failure_does_not_stop_the_others(
    test_database: Database, test_user: User, push: MagicMock
) -> None:
    test_database.add_reminder(test_user.id, None, "First", _NOW - timedelta(minutes=2))
    test_database.add_reminder(test_user.id, None, "Second", _NOW - timedelta(minutes=1))
    push.side_effect = [RuntimeError("push service down"), None]

    assert scheduler.send_due_reminders(_NOW) == 1
    assert push.call_count == 2
