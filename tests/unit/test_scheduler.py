"""The agent scheduler (src/agent/scheduler.py) against a real test database.

Runs unattended every minute in production, so a regression here goes unseen
longest. Only execute_agent is faked: due-ness, skipping, execution records
and schedule advancement all go through the real DB code.
"""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.agent import executor, scheduler
from src.agent.executor import AgentBlockedError
from src.agent.tools.request_approval import ApprovalRequestedException
from src.db.models import Database, User
from src.db.models.dataclasses import Agent
from src.utils.datetime_utils import utcnow_naive

EVERY_HOUR = "0 * * * *"


@pytest.fixture
def db(test_database: Database, monkeypatch: pytest.MonkeyPatch) -> Iterator[Database]:
    monkeypatch.setattr(scheduler, "db", test_database)
    yield test_database


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """The faked execute_agent; succeeds unless a test says otherwise."""
    fake = MagicMock(return_value=(True, None))
    monkeypatch.setattr(executor, "execute_agent", fake)
    return fake


def _due_agent(db: Database, user: User, name: str = "Briefing", **kwargs: Any) -> Agent:
    agent = db.create_agent(user.id, name, schedule=EVERY_HOUR, **kwargs)
    db.update_agent_next_run(agent.id, utcnow_naive() - timedelta(minutes=1))
    return db.get_agent(agent.id, user.id)  # type: ignore[return-value]


def _executions(db: Database, agent: Agent) -> list[Any]:
    return db.get_recent_executions(agent.user_id, limit=50)


def test_a_due_agent_runs_and_its_execution_completes(
    db: Database, test_user: User, run: MagicMock
) -> None:
    agent = _due_agent(db, test_user)
    result = scheduler.run_scheduled_agents()
    assert (result.executed, result.failed, result.skipped) == (1, 0, 0)
    assert run.call_args.args[0].id == agent.id
    assert run.call_args.args[2] == "scheduled"
    assert [e.status for e in _executions(db, agent)] == ["completed"]


def test_agents_not_due_or_disabled_do_not_run(
    db: Database, test_user: User, run: MagicMock
) -> None:
    later = db.create_agent(test_user.id, "Later", schedule=EVERY_HOUR)
    db.update_agent_next_run(later.id, utcnow_naive() + timedelta(hours=1))
    _due_agent(db, test_user, "Off", enabled=False)
    scheduler.run_scheduled_agents()
    run.assert_not_called()


def test_an_agent_waiting_for_approval_is_skipped(
    db: Database, test_user: User, run: MagicMock
) -> None:
    agent = _due_agent(db, test_user)
    db.create_approval_request(agent.id, test_user.id, "send_message", {}, "Send it?")
    result = scheduler.run_scheduled_agents()
    assert result.skipped == 1
    run.assert_not_called()


def test_an_agent_already_running_is_not_started_twice(
    db: Database, test_user: User, run: MagicMock
) -> None:
    agent = _due_agent(db, test_user)
    db.create_execution(agent.id, "manual")  # status "running"
    result = scheduler.run_scheduled_agents()
    assert result.skipped == 1
    run.assert_not_called()


def test_a_failed_run_is_recorded_and_the_schedule_moves_on(
    db: Database, test_user: User, run: MagicMock
) -> None:
    """Without advancing next_run_at a failing agent would retry every minute."""
    agent = _due_agent(db, test_user)
    run.return_value = (False, "Calendar token expired")
    result = scheduler.run_scheduled_agents()
    assert result.failed == 1
    execution = _executions(db, agent)[0]
    assert (execution.status, execution.error_message) == ("failed", "Calendar token expired")
    refreshed = db.get_agent(agent.id, test_user.id)
    assert refreshed is not None and refreshed.next_run_at is not None
    assert refreshed.next_run_at > utcnow_naive()


def test_a_crash_is_recorded_and_the_schedule_moves_on(
    db: Database, test_user: User, run: MagicMock
) -> None:
    agent = _due_agent(db, test_user)
    run.side_effect = RuntimeError("model unavailable")
    result = scheduler.run_scheduled_agents()
    assert result.failed == 1
    execution = _executions(db, agent)[0]
    assert (execution.status, execution.error_message) == ("failed", "model unavailable")
    refreshed = db.get_agent(agent.id, test_user.id)
    assert refreshed is not None and refreshed.next_run_at is not None
    assert refreshed.next_run_at > utcnow_naive()


@pytest.mark.parametrize(
    ("outcome", "counter"),
    [
        ({"return_value": ("waiting_approval", None)}, "waiting_approval"),
        ({"side_effect": ApprovalRequestedException("approval-1", "Send it?")}, "waiting_approval"),
        ({"side_effect": AgentBlockedError("blocked")}, "skipped"),
    ],
)
def test_approval_and_blocked_outcomes_are_counted_not_failed(
    db: Database, test_user: User, run: MagicMock, outcome: dict[str, Any], counter: str
) -> None:
    _due_agent(db, test_user)
    run.configure_mock(**outcome)
    result = scheduler.run_scheduled_agents()
    assert getattr(result, counter) == 1
    assert result.failed == 0


def test_one_failing_agent_does_not_stop_the_others(
    db: Database, test_user: User, run: MagicMock
) -> None:
    first = _due_agent(db, test_user, "First")
    _due_agent(db, test_user, "Second")
    run.side_effect = lambda agent, *_: (
        (_ for _ in ()).throw(RuntimeError("boom")) if agent.id == first.id else (True, None)
    )
    result = scheduler.run_scheduled_agents()
    assert (result.executed, result.failed) == (1, 1)
