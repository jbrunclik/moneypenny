"""The run gates (S9 hardening; one approval mechanism, step 2).

A destructive operation in an unattended run - or a write without the write
level - needs the user's yes to exactly that call: without it the gate files
the call's card (a run proposal with its full arguments) and pauses the run.
Approving lets the identical call run once; a different call asks again.
Prompt-level confirmation alone is exactly what prompt injection bypasses.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import pytest

from src.agent.run_context import JobContext, clear_job_context, set_job_context
from src.agent.tools.permission_check import check_autonomous_permission
from src.agent.tools.request_approval import ApprovalRequestedException
from src.db.models import use_database

if TYPE_CHECKING:
    from src.db.models import Database, Proposal, User


@pytest.fixture
def agent_ctx(test_database: Database, test_user: User) -> Iterator[Any]:
    """A real agent as the current run, on the test database."""
    with use_database(test_database):
        agent = test_database.create_standing_chat(user_id=test_user.id, name="Gate Test")
        set_job_context(
            JobContext(item=agent.job, user=test_user, name=agent.name, trigger_chain=[agent.id])
        )
        yield agent
        clear_job_context()


def _blocked(tool: str, args: dict[str, Any]) -> Proposal:
    """The call pauses the run; the card it filed."""
    from src.agent.run_context import get_job_context
    from src.db.models import db

    with pytest.raises(ApprovalRequestedException) as raised:
        check_autonomous_permission(tool, args)
    run = get_job_context()
    assert run is not None
    card = db.get_proposal(raised.value.approval_id, run.user.id)
    assert card is not None
    return card


def _approve(card: Proposal, test_database: Database) -> None:
    """The user approves the card (the resume itself is not under test here)."""
    assert test_database.claim_proposal(card.id, "approved", 0, "button")


class TestDestructiveApprovalGate:
    def test_no_agent_context_allows(self) -> None:
        clear_job_context()
        # Interactive/plain chat: the user is driving - no gate
        check_autonomous_permission("todoist", {"operation": "delete_task"})

    def test_non_destructive_action_allows(self, agent_ctx: Any) -> None:
        check_autonomous_permission("todoist", {"operation": "add_task"})

    def test_a_destructive_call_files_its_card(self, agent_ctx: Any) -> None:
        card = _blocked("todoist", {"operation": "delete_task", "task_id": "t1"})

        assert (card.origin, card.kind, card.job_id, card.state) == (
            "run",
            "agent_action",
            agent_ctx.id,
            "pending",
        )
        assert card.summary == "Todoist: delete task"
        assert card.details == {"Task id": "t1"}
        assert [o["label"] for o in card.options] == ["Approve"]  # never "Always allow" a delete

    def test_the_approved_call_runs_exactly_once(
        self, agent_ctx: Any, test_database: Database
    ) -> None:
        call = {"operation": "delete_task", "task_id": "t1"}
        _approve(_blocked("todoist", call), test_database)

        check_autonomous_permission("todoist", call)  # the approved call
        _blocked("todoist", call)  # once only

    def test_another_call_does_not_spend_the_approval(
        self, agent_ctx: Any, test_database: Database
    ) -> None:
        _approve(_blocked("todoist", {"operation": "delete_task", "task_id": "t1"}), test_database)

        other = _blocked("todoist", {"operation": "delete_task", "task_id": "t2"})

        assert other.details == {"Task id": "t2"}  # a new card for the other task
        check_autonomous_permission("todoist", {"operation": "delete_task", "task_id": "t1"})

    def test_a_declined_card_authorizes_nothing(
        self, agent_ctx: Any, test_database: Database
    ) -> None:
        call = {"operation": "delete_project", "project_id": "p1"}
        card = _blocked("todoist", call)
        test_database.claim_proposal(card.id, "declined", None, "button")

        _blocked("todoist", call)


class TestArchiveAndRescheduleGates:
    def test_archive_project_gated(self, agent_ctx: Any) -> None:
        _blocked("todoist", {"operation": "archive_project", "project_id": "p1"})

    def test_update_event_reschedule_gated(self, agent_ctx: Any) -> None:
        _blocked(
            "google_calendar",
            {"operation": "update_event", "event_id": "e1", "start_time": "2026-06-13T09:00"},
        )

    def test_update_event_attendee_change_gated(self, agent_ctx: Any) -> None:
        _blocked(
            "google_calendar",
            {"operation": "update_event", "event_id": "e1", "attendees": ["a@b.c"]},
        )

    def test_update_event_cosmetic_edit_allowed(self, agent_ctx: Any) -> None:
        # Renames/description tweaks are reversible and stay ungated
        check_autonomous_permission(
            "google_calendar", {"operation": "update_event", "event_id": "e1"}
        )
