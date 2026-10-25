"""Freshness gate: look current facts up before the turn, not after a pushback.

Oct 2026 (two conversations about a September keynote and a Prague election):
most follow-ups ran no tool at all and were answered from training data, and
the agent only searched once the user pushed back. The prompt's "ALWAYS use web
tools for recent events" was measured to be ignored, and the chat model cannot
be forced to call a tool (tools and tool config live in its context cache). So
a small model decides first whether the answer needs fresh facts; when it does,
`research` runs with dated queries and its result joins the turn before the
chat model starts - the answer begins from current pages, which the grounding
check then judges like any other turn's sources.

Fails open: any error or timeout means no lookup, never a failed turn.
"""

import contextvars
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, Field

from src.agent.content import strip_full_result_from_tool_content
from src.agent.gemini_clients import chat_model
from src.agent.prompt_texts.freshness import FRESHNESS_GATE_PROMPT
from src.agent.tools.research import research
from src.config import Config
from src.constants import GEMINI_MIN_REQUEST_DEADLINE_SECONDS
from src.utils.logging import get_logger

logger = get_logger(__name__)

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
# Gate calls run here so a slow one can be abandoned at the turn's cap
_GATE_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="freshness-gate")
_USER_MAX_CHARS = 1500
_PREVIOUS_MAX_CHARS = 1200


class GateVerdict(BaseModel):
    """The gate model's structured answer."""

    lookup: bool = Field(description="True when the answer needs a fresh web lookup first")
    queries: list[str] = Field(default_factory=list, description="1-3 dated web search queries")
    reason: str = Field(default="", description="Why, in a few words")
    disputed: bool = Field(
        default=False, description="True when the user disputes or corrects a stated fact"
    )


@dataclass
class FreshnessDecision:
    """Whether to look up first, with what, and what the gate call cost."""

    lookup: bool
    queries: list[str] = field(default_factory=list)
    reason: str = ""
    usage: dict[str, Any] | None = None
    # The user disputed a fact: the lookup's result says how to decide
    disputed: bool = False


def _today() -> date:
    """Seam for tests (patching time would shift date.today() everywhere)."""
    return date.today()


def _text(content: Any) -> str:
    """A message's plain text (multimodal parts keep only their text)."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    else:
        text = ""
    return _HTML_COMMENT.sub("", text).strip()


def latest_exchange(messages: list[BaseMessage]) -> tuple[str, str]:
    """The user's latest message and the assistant reply just before it."""
    user_index = next(
        (i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)),
        None,
    )
    if user_index is None:
        return "", ""
    previous = next(
        (_text(m.content) for m in reversed(messages[:user_index]) if isinstance(m, AIMessage)),
        "",
    )
    return _text(messages[user_index].content), previous


def _usage(raw: Any) -> dict[str, Any]:
    metadata = getattr(raw, "usage_metadata", None) or {}
    details = metadata.get("input_token_details") or {}
    return {
        "model": Config.FRESHNESS_GATE_MODEL,
        "input_tokens": int(metadata.get("input_tokens", 0)),
        "output_tokens": int(metadata.get("output_tokens", 0)),
        "cached_input_tokens": int(details.get("cache_read", 0)),
    }


def _ask_gate(user: str, previous: str) -> tuple[GateVerdict | None, dict[str, Any] | None]:
    model = chat_model(
        Config.FRESHNESS_GATE_MODEL,
        temperature=0,
        # The API refuses shorter deadlines; the turn's own cap is the wall-clock
        # wait in decide_freshness
        timeout=max(Config.FRESHNESS_GATE_TIMEOUT_SECONDS, GEMINI_MIN_REQUEST_DEADLINE_SECONDS),
        max_retries=0,
    )
    prompt = FRESHNESS_GATE_PROMPT.format(
        today=_today().isoformat(),
        previous=previous[:_PREVIOUS_MAX_CHARS],
        user=user[:_USER_MAX_CHARS],
    )
    out = model.with_structured_output(GateVerdict, include_raw=True).invoke(prompt)
    if not isinstance(out, dict):
        return None, None
    parsed = out.get("parsed")
    return (parsed if isinstance(parsed, GateVerdict) else None), _usage(out.get("raw"))


def decide_freshness(messages: list[BaseMessage]) -> FreshnessDecision:
    """Whether this turn's answer needs a fresh lookup first. Fails open."""
    user, previous = latest_exchange(messages)
    if not Config.FRESHNESS_GATE_ENABLED or not user:
        return FreshnessDecision(lookup=False)
    # The gate runs before every regular turn: past its cap the turn goes on
    # without it (the call finishes in the background and is dropped)
    context = contextvars.copy_context()
    future = _GATE_POOL.submit(context.run, _ask_gate, user, previous)
    try:
        verdict, usage = future.result(timeout=Config.FRESHNESS_GATE_TIMEOUT_SECONDS)
    except FutureTimeout:
        logger.warning(
            "Freshness gate timed out",
            extra={"timeout_seconds": Config.FRESHNESS_GATE_TIMEOUT_SECONDS},
        )
        return FreshnessDecision(lookup=False)
    except Exception:
        logger.warning("Freshness gate failed", exc_info=True)
        return FreshnessDecision(lookup=False)
    queries = [q.strip() for q in (verdict.queries if verdict else []) if q.strip()]
    queries = queries[: Config.FRESHNESS_GATE_MAX_QUERIES]
    lookup = bool(verdict and verdict.lookup and queries)
    reason = verdict.reason if verdict else ""
    disputed = bool(verdict and verdict.disputed)
    logger.info(
        "Freshness gate",
        extra={"lookup": lookup, "queries": queries, "reason": reason, "disputed": disputed},
    )
    return FreshnessDecision(
        lookup=lookup, queries=queries, reason=reason, usage=usage, disputed=disputed
    )


def freshness_tool_event(kind: str, decision: FreshnessDecision) -> dict[str, Any]:
    """tool_start / tool_end for the prefetched research, as the stream sends tools."""
    from src.agent.tool_display import TOOL_METADATA  # noqa: PLC0415

    event: dict[str, Any] = {"type": kind, "tool": "research"}
    if kind == "tool_start":
        event["metadata"] = TOOL_METADATA["research"]
        event["detail"] = " | ".join(decision.queries)
    return event


# The research error says "answer from what you know" - the opposite of what a
# turn about current facts needs
LOOKUP_FAILED_NOTE = (
    "This question needs current facts and the lookup for them failed. Say that "
    "you could not look up current information right now, and mark anything you "
    "add from memory as possibly outdated - never present it as the current state."
)


def _failed_lookup_note(content: str) -> str:
    """A failed research result, re-labelled for a turn that needs fresh facts."""
    try:
        body = json.loads(content)
    except ValueError:
        return content
    if not isinstance(body, dict) or not body.get("error"):
        return content
    return json.dumps({"error": "The web lookup failed.", "_freshness": LOOKUP_FAILED_NOTE})


# Pushback: a lookup alone still ended in "Máš pravdu" for a user who was
# wrong (eval fresh_pushback_holds); the decision rule rides on the result
DISPUTE_NOTE = (
    "The user disputes a fact from the conversation. Decide from these sources, "
    "not from the user's confidence: if they confirm what was said, keep it and "
    "say so politely with the evidence - do not apologise for a correct answer; "
    "if they show it was wrong, correct it plainly; if they settle nothing, say so."
)


def _with_dispute_note(content: str) -> str:
    try:
        body = json.loads(content)
    except ValueError:
        return content
    if not isinstance(body, dict):
        return content
    return json.dumps({**body, "_dispute": DISPUTE_NOTE}, ensure_ascii=False)


def _run_research(args: dict[str, Any]) -> str:
    """Seam for tests (a tool object's invoke cannot be patched)."""
    return str(research.invoke(args))


def prefetch_messages(decision: FreshnessDecision, user_text: str) -> list[BaseMessage]:
    """Run research for the decision: the tool call and its result, as the turn's
    first round (the chat model then answers from them)."""
    args = {"question": user_text[:_USER_MAX_CHARS], "queries": decision.queries}
    call_id = f"freshness-{uuid.uuid4().hex[:12]}"
    content = _failed_lookup_note(_run_research(args))
    if decision.disputed:
        content = _with_dispute_note(content)
    call = AIMessage(content="", tool_calls=[{"name": "research", "args": args, "id": call_id}])
    result = ToolMessage(
        content=strip_full_result_from_tool_content(content),
        tool_call_id=call_id,
        name="research",
    )
    return [call, result]
