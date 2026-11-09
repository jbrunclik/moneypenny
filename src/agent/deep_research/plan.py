"""The plan a deep-research run executes: the accepted (and maybe edited)
offer - its card's payload (a deep_research proposal, src/agent/deep_research/offer.py)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from src.agent.deep_research.estimate import estimate
from src.agent.deep_research.offer import KIND, seconds_open, validate_plan
from src.agent.proposals import ProposalFailedError, log_resolved
from src.config import Config
from src.db.models import Proposal, ProposalOption, db
from src.utils.logging import get_logger

logger = get_logger(__name__)


class OfferNotFoundError(LookupError):
    """No offer with that id in this conversation."""


class OfferConflictError(RuntimeError):
    """The offer was already started, declined or superseded."""


STARTED = "Started"
_STATE_WORDS = {
    "pending": "offered",
    "applying": "started",
    "approved": "started",
    "declined": "declined",
    "expired": "closed",
    "superseded": "replaced",
    "failed": "closed",
}


@dataclass
class DeepResearchPlan:
    """What one run researches (spec: docs/superpowers/specs/2026-10-03-deep-research-design.md)."""

    offer_message_id: str
    question: str
    context: str
    sub_questions: list[str]
    offered_sub_questions: list[str]
    round: int = 1
    estimate: dict[str, int] = field(default_factory=dict)
    previous_report: str | None = None


def _questions(offer: Mapping[str, object]) -> list[str]:
    value = offer.get("sub_questions")
    return [str(q) for q in value] if isinstance(value, list) else []


def _open_card(conv_id: str, user_id: str, proposal_id: str) -> Proposal:
    """The conversation's open research card, or raise."""
    card = db.get_proposal(proposal_id, user_id)
    if card is None or card.conversation_id != conv_id or card.kind != KIND:
        raise OfferNotFoundError(proposal_id)
    if card.state != "pending" or card.message_id is None:
        raise OfferConflictError(f"This research offer was already {_STATE_WORDS[card.state]}.")
    return card


def _final(offer: dict[str, Any], items: list[str], context: str) -> dict[str, Any]:
    """The offer with the plan that runs (the editor may have changed it)."""
    return {
        **offer,
        "final_sub_questions": items,
        "final_context": context,
        "final_estimate": estimate(len(items)),
    }


def _log_started(card: Proposal, final: dict[str, Any], by: str) -> None:
    items, offered = final["final_sub_questions"], list(final.get("sub_questions") or [])
    logger.info(
        "Deep research started",
        extra={
            "conversation_id": card.conversation_id,
            "offer_message_id": card.message_id,
            "kind": final.get("kind"),
            "items": len(items),
            "added": len([i for i in items if i not in offered]),
            "removed": len([i for i in offered if i not in items]),
            "context_edited": final["final_context"] != str(final.get("context") or ""),
            "decision_seconds": seconds_open(final),
            "estimate": final["final_estimate"],
            "resolved_by": by,
        },
    )


def _plan(card: Proposal, final: dict[str, Any]) -> DeepResearchPlan:
    message_id = card.message_id or ""
    report = None
    if final.get("kind") == "followup":
        message = db.get_message_by_id(message_id)
        report = message.content if message else None
    return DeepResearchPlan(
        offer_message_id=message_id,
        question=str(final.get("question") or ""),
        context=final["final_context"],
        sub_questions=final["final_sub_questions"],
        offered_sub_questions=list(final.get("sub_questions") or []),
        round=int(final.get("round") or 1),
        estimate=final["final_estimate"],
        previous_report=report,
    )


def start_plan(
    conv_id: str, user_id: str, proposal_id: str, sub_questions: list[str], context: str
) -> DeepResearchPlan:
    """Start's plan: validate the user's final plan and claim the card with
    it (one atomic write - a second device's start conflicts).

    Raises PlanError (bad plan), OfferNotFoundError, OfferConflictError.
    """
    card = _open_card(conv_id, user_id, proposal_id)
    option = card.options[0]
    items, context = validate_plan(sub_questions, context)
    final = _final(dict(option["payload"]), items, context)
    if not db.claim_proposal(
        card.id, "approved", 0, "button", options=[{**option, "payload": final}]
    ):
        raise OfferConflictError("This research offer was already decided.")
    db.finish_proposal(card.id, "approved", STARTED)
    _log_started(card, final, "button")
    log_resolved(card, "approved", "button")
    return _plan(card, final)


def typed_start_plan(answered: list[Proposal]) -> DeepResearchPlan | None:
    """A typed yes approved a research card: its plan, unedited (this turn is the run)."""
    card = next((p for p in answered if p.kind == KIND and p.state == "approved"), None)
    if card is None:
        return None
    option = card.options[0]
    offer = option["payload"]
    final = _final(dict(offer), _questions(offer), str(offer.get("context") or ""))
    db.set_proposal_options(card.id, [{**option, "payload": final}])
    _log_started(card, final, "typed")
    return _plan(card, final)


def apply_research(proposal: Proposal, option: ProposalOption) -> str:
    """A typed yes: the turn it arrived in runs the research (typed_start_plan)."""
    if not Config.DEEP_RESEARCH_ENABLED:
        raise ProposalFailedError("Deep research is turned off.")
    return STARTED


def decline_research(proposal: Proposal) -> None:
    """No thanks (or a typed no)."""
    offer = proposal.options[0]["payload"]
    logger.info(
        "Deep research declined",
        extra={
            "conversation_id": proposal.conversation_id,
            "offer_message_id": proposal.message_id,
            "kind": offer.get("kind"),
            "sub_questions": len(_questions(offer)),
            "decision_seconds": seconds_open(offer),
        },
    )
