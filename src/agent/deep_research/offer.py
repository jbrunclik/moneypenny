"""Deep-research offers: plan validation, the stored offer, extraction.

The agent calls propose_deep_research (src/agent/tools/deep_research.py); its
arguments are read off the turn's tool calls when the reply is saved, and the
offer becomes that reply's card: a deep_research proposal whose one option
(Start) carries the plan (docs/features/proposals.md). A report's follow-up
offer is filed the same way on the report.
"""

import re
import uuid
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from src.agent.deep_research.estimate import estimate, estimate_rates
from src.config import Config
from src.db.models import Proposal, db
from src.db.models.timestamps import from_db
from src.utils.clock import to_api, utc_now

TOOL_NAME = "propose_deep_research"
KIND = "deep_research"
START_LABEL = "Start"


class PlanError(ValueError):
    """A plan the user or the agent sent is not runnable."""


def validate_plan(sub_questions: list[str], context: str) -> tuple[list[str], str]:
    """Clean sub-questions and context, or raise PlanError."""
    items = [item.strip() for item in sub_questions if isinstance(item, str) and item.strip()]
    if not items:
        raise PlanError("Add at least one question or topic.")
    if len(items) > Config.DEEP_RESEARCH_MAX_SUB_QUESTIONS:
        raise PlanError(f"At most {Config.DEEP_RESEARCH_MAX_SUB_QUESTIONS} questions or topics.")
    if any(len(item) > Config.DEEP_RESEARCH_MAX_ITEM_CHARS for item in items):
        raise PlanError(
            f"Keep each question under {Config.DEEP_RESEARCH_MAX_ITEM_CHARS} characters."
        )
    context = (context or "").strip()
    if len(context) > Config.DEEP_RESEARCH_MAX_CONTEXT_CHARS:
        raise PlanError(
            f"Keep the context under {Config.DEEP_RESEARCH_MAX_CONTEXT_CHARS} characters."
        )
    return items, context


def build_offer(args: dict[str, Any], kind: str = "initial", round_: int = 1) -> dict[str, Any]:
    """The stored offer for validated tool arguments (raises PlanError)."""
    items, context = validate_plan(
        list(args.get("sub_questions") or []), str(args.get("context") or "")
    )
    rates = estimate_rates()
    return {
        "question": str(args.get("question") or "").strip(),
        "context": context,
        "sub_questions": items,
        "estimate": estimate(len(items), rates),
        "rates": rates,
        "status": "offered",
        "autostart": bool(args.get("run_now")),
        "kind": kind,
        "round": round_,
        "created_at": to_api(utc_now()),
    }


def seconds_open(offer: dict[str, Any]) -> int | None:
    """Seconds since the offer was made (time to decision, for telemetry)."""
    try:
        # Offers made before Oct 27 2026 hold local-naive times: no answer
        created = from_db(str(offer["created_at"]))
    except KeyError, ValueError:
        return None
    return round((utc_now() - created).total_seconds())


# The user's own words that ask for a run now (cs/en). run_now from the model
# alone is not enough: it was seen setting it on an ordinary question.
_EXPLICIT_REQUEST = re.compile(
    r"deep\s*research|důkladn|hloubkov|prozkoum|in[\s-]depth|thorough",
    re.IGNORECASE,
)


def asks_for_deep_research(user_text: str) -> bool:
    """Whether the user's message explicitly asks for in-depth research."""
    return bool(_EXPLICIT_REQUEST.search(user_text))


def extract_offer(result_messages: list[BaseMessage], user_text: str = "") -> dict[str, Any] | None:
    """The offer from the turn's last propose_deep_research call, if valid.

    It autostarts only when the model set run_now AND the user's message
    explicitly asked for in-depth research; otherwise the user decides.
    """
    args: dict[str, Any] | None = None
    for msg in result_messages:
        if isinstance(msg, AIMessage):
            for call in msg.tool_calls:
                if call.get("name") == TOOL_NAME:
                    args = call.get("args") or {}
    if args is None:
        return None
    try:
        offer = build_offer(args)
    except PlanError:
        return None
    offer["autostart"] = offer["autostart"] and asks_for_deep_research(user_text)
    return offer


def file_offer_card(
    offer: dict[str, Any], conversation_id: str, user_id: str, request_id: str
) -> Proposal:
    """File the offer as this turn's card (the saved reply links it); it
    replaces the conversation's open offer, as one plan is on the table."""
    card = db.create_proposal(
        Proposal(
            id=str(uuid.uuid4()),
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=None,
            request_id=request_id,
            kind=KIND,
            summary=str(offer.get("question") or "Deep research"),
            details={},
            options=[{"label": START_LABEL, "description": "", "payload": offer}],
            state="pending",
            chosen=None,
            result=None,
            resolved_by=None,
            reported=False,
            created_at=utc_now(),
            resolved_at=None,
        )
    )
    db.supersede_open_proposals(conversation_id, KIND, card.id)
    return card
