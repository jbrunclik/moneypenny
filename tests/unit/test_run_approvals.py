"""A run's card: parked under the waiting message, answered once, and the
answer resumes or ends exactly that run (docs/features/proposals.md)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

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

if TYPE_CHECKING:
    from src.db.models import Database, Proposal, User


@pytest.fixture
def run(test_database: Database, test_user: User) -> Iterator[tuple[Any, JobContext]]:
    with (
        use_database(test_database),
        patch("src.agent.run_context.send_push_to_user"),
    ):
        agent = test_database.create_standing_chat(test_user.id, "Coach", grants=["todoist"])
        context = JobContext(
            item=agent.job, user=test_user, name=agent.name, trigger_chain=[agent.id]
        )
        set_job_context(context)
        yield agent, context
        clear_job_context()


def _park(db: Database, context: JobContext, args: dict[str, Any]) -> Proposal:
    """The run makes a gated call and is parked on its card."""
    execution = db.create_execution(context.item.id, "scheduled")
    with pytest.raises(ApprovalRequestedException) as raised:
        check_autonomous_permission("todoist", args)
    record_approval_request(raised.value, context, context.item.conversation_id or "", execution.id)
    card = db.get_proposal(raised.value.approval_id, context.user.id)
    assert card is not None
    return card


def test_a_parked_run_shows_its_card_under_the_waiting_message(
    run: tuple[Any, JobContext], test_database: Database
) -> None:
    agent, context = run

    card = _park(test_database, context, {"operation": "add_task", "content": "Buy milk"})

    [message] = test_database.get_messages(agent.conversation_id)
    assert card.message_id == message.id and card.execution_id is not None
    assert message.content.startswith("**Waiting for your approval**")
    assert "[approval-request:" not in message.content


def test_approving_resumes_that_run_with_the_call_to_reissue(
    run: tuple[Any, JobContext], test_database: Database
) -> None:
    agent, context = run
    card = _park(test_database, context, {"operation": "add_task", "content": "Buy milk"})

    with patch("src.agent.run_approvals._resume") as resume:
        done = resolve(card, 0, "button")

    assert done.state == "approved"
    [_, note] = test_database.get_messages(agent.conversation_id)
    assert note.content.startswith("[Action approved: Todoist: add task]")
    assert '"content": "Buy milk"' in note.content
    resume.assert_called_once()
    [execution] = test_database.get_job_runs(agent.id, limit=1)
    assert execution.status == "completed"


def test_always_allow_grants_the_write_level(
    run: tuple[Any, JobContext], test_database: Database
) -> None:
    agent, context = run
    card = _park(test_database, context, {"operation": "add_task", "content": "Buy milk"})

    with patch("src.agent.run_approvals._resume"):
        resolve(card, 1, "button")

    job = test_database.get_item(agent.id, agent.user_id)
    assert job is not None and "todoist:write" in (job.grants or [])


def test_declining_ends_the_run(run: tuple[Any, JobContext], test_database: Database) -> None:
    agent, context = run
    card = _park(test_database, context, {"operation": "add_task", "content": "Buy milk"})

    with patch("src.agent.run_approvals._resume") as resume:
        resolve(card, None, "button")

    resume.assert_not_called()
    [execution] = test_database.get_job_runs(agent.id, limit=1)
    assert execution.status == "rejected"
    assert test_database.get_messages(agent.conversation_id)[-1].content.startswith(
        "[Action rejected:"
    )


def test_two_paused_runs_each_resume_their_own(
    run: tuple[Any, JobContext], test_database: Database
) -> None:
    _agent, context = run
    first = _park(test_database, context, {"operation": "add_task", "content": "A"})
    second = _park(test_database, context, {"operation": "add_task", "content": "B"})

    with patch("src.agent.run_approvals._resume"):
        resolve(second, 0, "button")

    runs = {r.id: r.status for r in test_database.get_job_runs(context.item.id)}
    assert runs[second.execution_id or ""] == "completed"
    assert runs[first.execution_id or ""] == "waiting_approval"


def test_an_unanswered_card_expires_and_closes_its_run(
    run: tuple[Any, JobContext], test_database: Database
) -> None:
    from datetime import timedelta

    from src.agent.run_approvals import expire_stale_run_cards
    from src.utils.clock import utc_now

    agent, context = run
    card = _park(test_database, context, {"operation": "add_task", "content": "Buy milk"})

    assert expire_stale_run_cards(utc_now() + timedelta(hours=25)) == 1

    expired = test_database.get_proposal(card.id, card.user_id)
    assert expired is not None and expired.state == "expired"
    [execution] = test_database.get_job_runs(agent.id, limit=1)
    assert execution.status == "failed" and "approval" in (execution.error_message or "")
