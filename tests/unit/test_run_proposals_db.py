"""Run proposals: an unattended run's request for a yes (step 2 of the one
approval mechanism; docs/features/proposals.md)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

from src.db.models import Proposal
from src.utils.clock import utc_now

if TYPE_CHECKING:
    from src.db.models import Database, User


def _run_card(
    db: Database, user: User, job_id: str, conv_id: str, signature: str = "sig-1", hours: float = 24
) -> Proposal:
    payload: dict[str, object] = {
        "tool": "todoist",
        "args": {"operation": "add_task"},
        "signature": signature,
    }
    return db.create_proposal(
        Proposal(
            id=str(uuid.uuid4()),
            user_id=user.id,
            conversation_id=conv_id,
            message_id=None,
            request_id="",
            kind="agent_action",
            summary="Add a Todoist task",
            details={},
            options=[{"label": "Approve", "description": "", "payload": payload}],
            state="pending",
            chosen=None,
            result=None,
            resolved_by=None,
            reported=False,
            created_at=utc_now(),
            resolved_at=None,
            origin="run",
            job_id=job_id,
            execution_id="exec-1",
            expires_at=utc_now() + timedelta(hours=hours),
        )
    )


def _agent(db: Database, user: User) -> tuple[str, str]:
    agent = db.create_standing_chat(user.id, "Coach", schedule="0 20 * * *")
    return agent.id, agent.conversation_id or ""


def test_a_run_card_round_trips_its_run(test_database: Database, test_user: User) -> None:
    job_id, conv_id = _agent(test_database, test_user)
    made = _run_card(test_database, test_user, job_id, conv_id)

    got = test_database.get_proposal(made.id, test_user.id)

    assert got is not None
    assert (got.origin, got.job_id, got.execution_id) == ("run", job_id, "exec-1")
    assert test_database.has_pending_run_proposal(job_id) is True
    assert [p.id for p in test_database.pending_run_proposals(test_user.id)] == [made.id]


def test_chat_messages_never_expire_a_run_card(test_database: Database, test_user: User) -> None:
    job_id, conv_id = _agent(test_database, test_user)
    _run_card(test_database, test_user, job_id, conv_id)

    assert test_database.expire_proposals(conv_id) == 0
    assert test_database.has_pending_run_proposal(job_id) is True


def test_only_the_identical_call_consumes_an_approval(
    test_database: Database, test_user: User
) -> None:
    job_id, conv_id = _agent(test_database, test_user)
    card = _run_card(test_database, test_user, job_id, conv_id, signature="exact")
    test_database.claim_proposal(card.id, "approved", 0, "button")

    assert test_database.consume_run_approval(job_id, "different") is False
    assert test_database.consume_run_approval(job_id, "exact") is True
    assert test_database.consume_run_approval(job_id, "exact") is False  # once


def test_an_expired_run_card_is_swept(test_database: Database, test_user: User) -> None:
    job_id, conv_id = _agent(test_database, test_user)
    old = _run_card(test_database, test_user, job_id, conv_id, hours=-1)

    [swept] = test_database.expire_run_proposals(utc_now())

    assert swept.id == old.id
    assert test_database.has_pending_run_proposal(job_id) is False
