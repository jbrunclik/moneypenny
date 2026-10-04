"""Deep-research offers: plan validation, the stored offer, extraction.

The agent calls propose_deep_research (src/agent/tools/deep_research.py); its
arguments are read off the turn's tool calls when the reply is saved, so the
offer is stored on that assistant message (messages.research = {"offer": ...}).
"""

import re
from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from src.agent.deep_research.estimate import estimate, estimate_rates
from src.config import Config

TOOL_NAME = "propose_deep_research"


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
        "created_at": datetime.now().isoformat(),
    }


def seconds_open(offer: dict[str, Any]) -> int | None:
    """Seconds since the offer was made (time to decision, for telemetry)."""
    try:
        created = datetime.fromisoformat(str(offer["created_at"]))
    except KeyError, ValueError:
        return None
    return round((datetime.now() - created).total_seconds())


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
