"""The plan a deep-research run executes: the accepted (and maybe edited) offer."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.agent.deep_research.estimate import estimate
from src.agent.deep_research.offer import validate_plan
from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)


class OfferNotFound(LookupError):
    """No offer with that id in this conversation."""


class OfferConflict(RuntimeError):
    """The offer was already started, declined or superseded."""


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


def _open_offer(message: Any) -> tuple[dict[str, Any], bool]:
    """(offer, is_followup) of a message, or raise OfferConflict."""
    research = message.research or {}
    followup = (research.get("run") or {}).get("followup")
    offer = followup or research.get("offer")
    if not offer:
        raise OfferNotFound(message.id)
    if offer.get("status") != "offered":
        raise OfferConflict(f"This research offer was already {offer.get('status')}.")
    return offer, followup is not None


def start_plan(
    conv_id: str, offer_message_id: str, sub_questions: list[str], context: str
) -> DeepResearchPlan:
    """Validate the user's final plan, mark the offer started, return the plan.

    Raises PlanError (bad plan), OfferNotFound, OfferConflict.
    """
    message = db.get_message_by_id(offer_message_id)
    if message is None or message.conversation_id != conv_id:
        raise OfferNotFound(offer_message_id)
    offer, is_followup = _open_offer(message)
    items, context = validate_plan(sub_questions, context)
    final_estimate = estimate(len(items))
    started = {
        **offer,
        "status": "started",
        "final_sub_questions": items,
        "final_context": context,
        "final_estimate": final_estimate,
        "decided_at": datetime.now().isoformat(),
    }
    research = message.research or {}
    if is_followup:
        db.set_message_research(
            message.id, {**research, "run": {**research["run"], "followup": started}}
        )
    else:
        db.set_message_research(message.id, {**research, "offer": started})
    offered = list(offer.get("sub_questions") or [])
    logger.info(
        "Deep research started",
        extra={
            "conversation_id": conv_id,
            "offer_message_id": offer_message_id,
            "kind": offer.get("kind"),
            "items": len(items),
            "added": len([i for i in items if i not in offered]),
            "removed": len([i for i in offered if i not in items]),
            "estimate": final_estimate,
        },
    )
    return DeepResearchPlan(
        offer_message_id=offer_message_id,
        question=str(offer.get("question") or ""),
        context=context,
        sub_questions=items,
        offered_sub_questions=offered,
        round=int(offer.get("round") or 1),
        estimate=final_estimate,
        previous_report=message.content if is_followup else None,
    )


def decline_offer(message: Any) -> None:
    """Mark an open offer (or follow-up offer) declined."""
    offer, is_followup = _open_offer(message)
    declined = {**offer, "status": "declined", "decided_at": datetime.now().isoformat()}
    research = message.research or {}
    if is_followup:
        db.set_message_research(
            message.id, {**research, "run": {**research["run"], "followup": declined}}
        )
    else:
        db.set_message_research(message.id, {**research, "offer": declined})
    logger.info(
        "Deep research declined",
        extra={
            "conversation_id": message.conversation_id,
            "offer_message_id": message.id,
            "kind": offer.get("kind"),
        },
    )
