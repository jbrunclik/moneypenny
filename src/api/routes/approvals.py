"""Runs waiting on the user's card: GET /api/approvals (Command Center).

A run's card is a proposal (src/agent/run_approvals.py): it is answered
through /api/proposals/<id>/approve|decline like any card.
"""

from __future__ import annotations

from src.api.helpers.standing_responses import run_proposal_to_response
from src.api.routes.jobs import api
from src.api.schemas.jobs import PendingApprovalsResponse
from src.auth.jwt_auth import require_auth
from src.db.models import User, db


@api.route("/approvals", methods=["GET"])
@api.output(PendingApprovalsResponse)
@api.doc(responses=[401])
@require_auth
def list_pending_approvals(user: User) -> dict[str, object]:
    """The user's runs waiting on a card, with their standing chats' names."""
    names = {chat.id: chat.name for chat in db.list_standing_chats(user.id)}
    return {
        "pending_approvals": [
            run_proposal_to_response(p, names.get(p.job_id or "", "Agent"))
            for p in db.pending_run_proposals(user.id)
        ]
    }
