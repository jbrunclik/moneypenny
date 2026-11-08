"""The every-minute scheduler (src/agent/scheduler.py) against a real test database.

Runs unattended every minute in production, so a regression here goes unseen
longest. Since standing chats phase 2 an agent is a standing job: it runs in
the one pass over scheduled items. Only the model run is faked.
"""

from collections.abc import Iterator
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.agent import scheduler
from src.agent.item_runner import RunOutcome
from src.db.models import Database, User, use_database
from src.db.models.dataclasses import Agent
from src.utils.clock import utc_now

EVERY_HOUR = "0 * * * *"


@pytest.fixture
def db(test_database: Database, monkeypatch: pytest.MonkeyPatch) -> Iterator[Database]:
    monkeypatch.setattr(scheduler, "db", test_database)
    with use_database(test_database):
        yield test_database


@pytest.fixture
def run() -> Iterator[MagicMock]:
    """The faked model run; reports unless a test says otherwise."""
    with (
        patch("src.agent.item_scheduler.run_model_item") as fake,
        patch("src.agent.item_runner.send_push_to_user"),
    ):
        fake.return_value = RunOutcome("report", "Good morning.")
        yield fake


def _due_agent(db: Database, user: User, name: str = "Briefing", **kwargs: object) -> Agent:
    agent = db.create_agent(user.id, name, schedule=EVERY_HOUR, **kwargs)  # type: ignore[arg-type]
    db.finish_item_run(agent.id, utc_now() - timedelta(minutes=1), None, 0, 0)
    return db.get_agent(agent.id, user.id)  # type: ignore[return-value]


def test_a_due_agent_runs_as_its_standing_job(
    db: Database, test_user: User, run: MagicMock
) -> None:
    agent = _due_agent(db, test_user)

    result = scheduler.run_scheduled_agents()

    assert result.items_run == 1
    assert run.call_args.args[0].id == agent.id
    assert [m.content for m in db.get_messages(agent.conversation_id or "")] == ["Good morning."]
    after = db.get_agent(agent.id, test_user.id)
    assert after is not None and after.next_run_at is not None
    assert after.next_run_at > utc_now()


def test_a_disabled_agent_does_not_run(db: Database, test_user: User, run: MagicMock) -> None:
    agent = _due_agent(db, test_user)
    db.update_agent(agent.id, test_user.id, enabled=False)

    scheduler.run_scheduled_agents()

    run.assert_not_called()


def test_items_are_counted(
    db: Database, test_user: User, run: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agent.item_scheduler import ItemsResult

    monkeypatch.setattr(scheduler, "run_due_items", lambda now: ItemsResult(fired=2, run=1))

    result = scheduler.run_scheduled_agents()

    assert (result.items_fired, result.items_run) == (2, 1)
