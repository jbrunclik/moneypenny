"""Proposals storage: one record for anything awaiting the user's yes
(docs/features/proposals.md)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from src.db.models import Proposal
from src.utils.clock import utc_now

if TYPE_CHECKING:
    from src.db.models import Database, User

_OPTION = {"label": "Set it up", "description": "", "payload": {"kind": "reminder", "text": "x"}}


def _proposal(
    conv_id: str, user_id: str, request_id: str = "req-1", kind: str = "schedule_item"
) -> Proposal:
    return Proposal(
        id=str(uuid.uuid4()),
        user_id=user_id,
        conversation_id=conv_id,
        message_id=None,
        request_id=request_id,
        kind=kind,
        summary="Reminder Thu 8:00: call the plumber",
        details={"When": "Thu 8:00"},
        options=[_OPTION],  # type: ignore[list-item]  # a literal ProposalOption
        state="pending",
        chosen=None,
        result=None,
        resolved_by=None,
        reported=False,
        created_at=utc_now(),
        resolved_at=None,
    )


def _conv(db: Database, user: User) -> str:
    return db.create_conversation(user.id).id


def test_create_and_get_round_trips_options(test_database: Database, test_user: User) -> None:
    conv_id = _conv(test_database, test_user)
    made = test_database.create_proposal(_proposal(conv_id, test_user.id))

    got = test_database.get_proposal(made.id, test_user.id)

    assert got is not None
    assert (got.options, got.details, got.state) == ([_OPTION], {"When": "Thu 8:00"}, "pending")
    assert test_database.get_proposal(made.id, "someone-else") is None


def test_claim_is_won_once(test_database: Database, test_user: User) -> None:
    conv_id = _conv(test_database, test_user)
    made = test_database.create_proposal(_proposal(conv_id, test_user.id))

    assert test_database.claim_proposal(made.id, "approved", 0, "button") is True
    assert test_database.claim_proposal(made.id, "declined", None, "button") is False
    test_database.finish_proposal(made.id, "approved", "Reminder set")

    got = test_database.get_proposal(made.id, test_user.id)
    assert got is not None
    assert (got.state, got.chosen, got.result, got.resolved_by) == (
        "approved",
        0,
        "Reminder set",
        "button",
    )
    assert got.resolved_at is not None


def test_link_sets_the_reply_for_a_request(test_database: Database, test_user: User) -> None:
    conv_id = _conv(test_database, test_user)
    mine = test_database.create_proposal(_proposal(conv_id, test_user.id, "req-1"))
    other = test_database.create_proposal(_proposal(conv_id, test_user.id, "req-2"))
    reply = test_database.add_message(conv_id, "assistant", "Shall I?")

    test_database.link_proposals("req-1", reply.id)

    assert test_database.proposals_for_messages([reply.id]) == {
        reply.id: [test_database.get_proposal(mine.id, test_user.id)]
    }
    linked = test_database.get_proposal(other.id, test_user.id)
    assert linked is not None and linked.message_id is None


def test_expire_by_conversation_and_by_message(test_database: Database, test_user: User) -> None:
    conv_id = _conv(test_database, test_user)
    a = test_database.create_proposal(_proposal(conv_id, test_user.id, "req-1"))
    b = test_database.create_proposal(_proposal(conv_id, test_user.id, "req-2"))
    reply = test_database.add_message(conv_id, "assistant", "Shall I?")
    test_database.link_proposals("req-1", reply.id)

    assert test_database.expire_proposals(conv_id, reply.id) == 1
    assert [p.id for p in test_database.pending_proposals(conv_id)] == [b.id]
    assert test_database.expire_proposals(conv_id) == 1
    assert test_database.pending_proposals(conv_id) == []
    expired = test_database.get_proposal(a.id, test_user.id)
    assert expired is not None and expired.state == "expired"


def test_unreported_and_mark_reported(test_database: Database, test_user: User) -> None:
    conv_id = _conv(test_database, test_user)
    made = test_database.create_proposal(_proposal(conv_id, test_user.id))
    assert test_database.unreported_proposals(conv_id) == []  # pending is not news yet

    test_database.claim_proposal(made.id, "declined", None, "button")
    assert [p.id for p in test_database.unreported_proposals(conv_id)] == [made.id]
    test_database.mark_reported([made.id])
    assert test_database.unreported_proposals(conv_id) == []


def test_a_proposal_change_bumps_the_conversation(test_database: Database, test_user: User) -> None:
    conv_id = _conv(test_database, test_user)
    made = test_database.create_proposal(_proposal(conv_id, test_user.id))
    before = test_database.get_sync_cursor()

    test_database.claim_proposal(made.id, "approved", 0, "button")

    assert test_database.get_sync_cursor() > before


def test_proposals_go_with_their_conversation(test_database: Database, test_user: User) -> None:
    conv_id = _conv(test_database, test_user)
    made = test_database.create_proposal(_proposal(conv_id, test_user.id))

    test_database.delete_conversation(conv_id, test_user.id)

    assert test_database.get_proposal(made.id, test_user.id) is None
