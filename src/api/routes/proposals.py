"""Proposal routes: approve or decline a card (docs/features/proposals.md).

On conversations.api: a proposal belongs to a conversation's reply. The
server applies the chosen option's stored payload (src/agent/proposals.py),
so what runs is what the card showed; a card answered, expired or not yet
shown under a saved reply is a 409.
"""

from __future__ import annotations

from src.agent.proposals import STREAM_STARTED, ProposalNotPendingError, resolve
from src.api.errors import raise_conflict_error, raise_not_found_error, raise_validation_error
from src.api.helpers.chat_turn import refuse_if_read_only
from src.api.rate_limiting import rate_limit_conversations
from src.api.routes.conversations import api
from src.api.schemas.proposals import ApproveProposalRequest, ProposalResponse
from src.api.utils import proposal_to_response
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.db.models import Proposal, User, db
from src.utils.clock import utc_now

_NOT_OPEN = "This card was already answered or is no longer open."


def _open_proposal(user: User, proposal_id: str) -> Proposal:
    """The user's proposal, if it can still be answered (404 / 409 otherwise)."""
    proposal = db.get_proposal(proposal_id, user.id)
    conv = db.get_conversation(proposal.conversation_id, user.id) if proposal else None
    if proposal is None or conv is None:
        raise_not_found_error("Proposal")
    refuse_if_read_only(conv)
    expired = proposal.expires_at is not None and proposal.expires_at <= utc_now()
    if proposal.state != "pending" or proposal.message_id is None or expired:
        raise_conflict_error(_NOT_OPEN, {"proposal": proposal_to_response(proposal)})
    return proposal


def _answer(user: User, proposal_id: str, choice: int | None) -> dict[str, object]:
    proposal = _open_proposal(user, proposal_id)
    if choice is not None and choice >= len(proposal.options):
        raise_validation_error(f"This card has {len(proposal.options)} option(s).", field="choice")
    try:
        return proposal_to_response(resolve(proposal, choice, "button"))
    except ProposalNotPendingError:  # another device or tap won the race
        current = db.get_proposal(proposal_id, user.id) or proposal
        raise_conflict_error(_NOT_OPEN, {"proposal": proposal_to_response(current)})


@api.route("/proposals/<proposal_id>/approve", methods=["POST"])
@api.output(ProposalResponse)
@api.doc(responses=[400, 404, 409, 429])
@rate_limit_conversations
@require_auth
@validate_request(ApproveProposalRequest)
def approve_proposal(
    user: User, data: ApproveProposalRequest, proposal_id: str
) -> dict[str, object]:
    """Approve a card: the server applies the chosen option exactly as shown.
    A deep-research card starts from its Start button (the run is a streamed
    turn), not here."""
    proposal = _open_proposal(user, proposal_id)
    if proposal.kind in STREAM_STARTED:
        raise_validation_error("Start it from its card.", field="choice")
    return _answer(user, proposal_id, data.choice)


@api.route("/proposals/<proposal_id>/decline", methods=["POST"])
@api.output(ProposalResponse)
@api.doc(responses=[404, 409, 429])
@rate_limit_conversations
@require_auth
def decline_proposal(user: User, proposal_id: str) -> dict[str, object]:
    """Decline a card ("Not now"): nothing is applied."""
    return _answer(user, proposal_id, None)
