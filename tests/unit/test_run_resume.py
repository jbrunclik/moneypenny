"""An approved run continues from the scheduler, so a deploy cannot lose it.

The continuation used to run on a daemon thread in the web worker: a deploy
killed it while the card said "Approved - continuing" (Nov 15 2026 audit;
docs/superpowers/specs/2026-11-15-run-resume-and-tick-deadline-design.md).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from src.agent import item_scheduler
from src.agent.item_runner import RunOutcome
from src.agent.proposals import resolve
from src.agent.run_context import (
    JobContext,
    clear_job_context,
    record_approval_request,
    set_job_context,
)
from src.agent.tools.permission_check import check_autonomous_permission
from src.agent.tools.request_approval import ApprovalRequestedException
from src.db.models import use_database
from src.utils.clock import utc_now

if TYPE_CHECKING:
    from src.db.models import Database, Proposal, ScheduledItem, User


@pytest.fixture
def agent(test_database: Database, test_user: User) -> Iterator[Any]:
    with (
        use_database(test_database),
        patch("src.agent.run_context.send_push_to_user"),
    ):
        made = test_database.create_standing_chat(test_user.id, "Coach", grants=["todoist"])
        yield made
        clear_job_context()


def _job(db: Database, agent: Any) -> ScheduledItem:
    job = db.get_item(agent.id, agent.user_id)
    assert job is not None
    return job


def _park(db: Database, agent: Any, user: User, content: str = "Buy milk") -> Proposal:
    """A run makes a gated call and is parked on its card."""
    context = JobContext(item=_job(db, agent), user=user, name=agent.name, trigger_chain=[])
    set_job_context(context)
    execution = db.create_execution(agent.id, "scheduled")
    with pytest.raises(ApprovalRequestedException) as raised:
        check_autonomous_permission("todoist", {"operation": "add_task", "content": content})
    record_approval_request(raised.value, context, agent.conversation_id, execution.id)
    clear_job_context()
    card = db.get_proposal(raised.value.approval_id, user.id)
    assert card is not None
    return card


@pytest.fixture
def runs() -> Iterator[MagicMock]:
    with (
        patch("src.agent.item_scheduler.run_model_item") as run,
        patch("src.agent.item_scheduler.deliver") as deliver,
    ):
        run.return_value = RunOutcome("report", "Added Buy milk.")
        run.deliver = deliver
        yield run


def test_approving_stores_the_continuation_and_starts_no_thread(
    agent: Any, test_database: Database, test_user: User
) -> None:
    card = _park(test_database, agent, test_user)

    with patch("threading.Thread") as thread:
        done = resolve(card, 0, "button")

    thread.assert_not_called()
    assert done.result == "Approved - continuing shortly."
    job = _job(test_database, agent)
    assert job.resume_message is not None
    assert "[Action approved:" in job.resume_message
    assert "Re-issue exactly:" in job.resume_message
    assert '"content": "Buy milk"' in job.resume_message


def test_the_next_pass_runs_the_continuation_off_schedule(
    agent: Any, test_database: Database, test_user: User, runs: MagicMock
) -> None:
    card = _park(test_database, agent, test_user)
    resolve(card, 0, "button")
    before = _job(test_database, agent)
    assert before.next_run_at > utc_now()  # not due: a resume is off-schedule

    result = item_scheduler.run_due_items(utc_now())

    assert result.run == 1
    kwargs = runs.call_args.kwargs
    assert kwargs["trigger"] == "approval"
    assert "Re-issue exactly:" in kwargs["message"]
    assert runs.deliver.call_args.kwargs["push"] is True
    after = _job(test_database, agent)
    assert after.resume_message is None
    assert (after.status, after.next_run_at, after.failures) == ("active", before.next_run_at, 0)


def test_a_paused_jobs_continuation_runs_and_it_stays_paused(
    agent: Any, test_database: Database, test_user: User, runs: MagicMock
) -> None:
    card = _park(test_database, agent, test_user)
    resolve(card, 0, "button")
    test_database.update_standing_chat(agent.id, test_user.id, enabled=False)

    assert item_scheduler.run_due_items(utc_now()).run == 1
    assert _job(test_database, agent).status == "paused"


def test_a_held_continuation_waits_and_keeps_its_message(
    agent: Any, test_database: Database, test_user: User, runs: MagicMock
) -> None:
    card = _park(test_database, agent, test_user)
    resolve(card, 0, "button")
    _park(test_database, agent, test_user, content="Eggs")  # a new card now pending

    assert item_scheduler.run_due_items(utc_now()).run == 0
    runs.assert_not_called()
    job = _job(test_database, agent)
    assert job.resume_message is not None
    assert job.status == "active"


def test_a_deleted_job_leaves_nothing_to_run(
    agent: Any, test_database: Database, test_user: User, runs: MagicMock
) -> None:
    card = _park(test_database, agent, test_user)
    resolve(card, 0, "button")
    test_database.delete_item(agent.id)

    assert item_scheduler.run_due_items(utc_now()).run == 0
    runs.assert_not_called()


def test_a_continuation_that_raises_counts_a_failure_and_keeps_its_message(
    agent: Any, test_database: Database, test_user: User, runs: MagicMock
) -> None:
    card = _park(test_database, agent, test_user)
    resolve(card, 0, "button")
    runs.side_effect = RuntimeError("boom")

    item_scheduler.run_due_items(utc_now())

    job = _job(test_database, agent)
    assert job.failures == 1
    assert job.resume_message is not None


def test_the_wait_is_logged(
    agent: Any, test_database: Database, test_user: User, runs: MagicMock
) -> None:
    card = _park(test_database, agent, test_user)
    resolve(card, 0, "button")

    with patch.object(item_scheduler.logger, "info") as info:
        item_scheduler.run_due_items(utc_now() + timedelta(seconds=40))

    [extra] = [
        c.kwargs["extra"] for c in info.call_args_list if c.args[0] == "Run resumed after cards"
    ]
    assert extra["item_id"] == agent.id
    assert extra["waited_s"] >= 39
