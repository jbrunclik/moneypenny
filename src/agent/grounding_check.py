"""Post-answer grounding check.

The Sep 2026 conversation sweep's most common correction was stale or invented
specifics, and prompt rules (GROUNDING_DIRECTIVE, the unverified-specifics rule)
were measured to have no effect. So after a turn that used web tools, a cheap
model judges every specific claim in the answer against the numbered pages the
turn read (src/agent/source_pages.py); the validated claims are stored as
annotations beside the unchanged answer (src/agent/grounding_annotations.py).
See docs/superpowers/specs/2026-10-03-grounding-annotations-design.md.
"""

import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.agent.content import extract_text_content, strip_echoed_msg_context
from src.agent.grounding_annotations import GroundingVerdict, summarize, validate_claims
from src.agent.price_net import missed_prices
from src.agent.prompt_texts.grounding import GROUNDING_CHECK_PROMPT
from src.agent.source_pages import WEB_TOOL_NAMES, SourcePage, turn_pages, uncited_web_text
from src.agent.tools.delegate import in_delegate_run
from src.config import Config
from src.constants import GEMINI_MIN_REQUEST_DEADLINE_SECONDS
from src.utils.logging import get_logger

logger = get_logger(__name__)

# The user's message is context, not evidence of a web fact; a cap keeps a
# pasted wall of text from crowding the sources out of the verifier call
_KNOWN_USER_TEXT_MAX_CHARS = 4000
# This turn's non-web tool results (calendar, Garmin, memory...) are facts the
# answer may state; capped like the user's message
_KNOWN_TOOL_TEXT_MAX_CHARS = 8000


def _now() -> datetime:
    """Seam for tests (patching time globally also shifts date.today())."""
    return datetime.now().astimezone()


def _turn_tool_facts(result_messages: list[BaseMessage]) -> str:
    """Text of this turn's successful non-web tool results, newest first, capped."""
    parts: list[str] = []
    total = 0
    for msg in reversed(result_messages):
        if isinstance(msg, HumanMessage):
            break  # history holds no ToolMessages, but stop at this turn anyway
        if not isinstance(msg, ToolMessage) or msg.name in WEB_TOOL_NAMES or msg.status == "error":
            continue
        text = extract_text_content(msg.content).strip()
        remaining = _KNOWN_TOOL_TEXT_MAX_CHARS - total
        if text and remaining > 0:
            parts.append(f"{msg.name}: {text[:remaining]}")
            total += len(parts[-1])
    return "\n".join(reversed(parts))


def known_facts(result_messages: list[BaseMessage]) -> str:
    """What the answer may state without a web source: today's date, the user's
    own message, and this turn's non-web tool results (the system prompt gives
    the model the date, so a verifier without it flags "today" as unsupported;
    a calendar event's time is not a web fact either)."""
    lines = [f"Today is {_now().strftime('%A %Y-%m-%d %H:%M %Z')}."]
    for msg in reversed(result_messages):
        if isinstance(msg, HumanMessage):
            text = strip_echoed_msg_context(extract_text_content(msg.content)).strip()
            if text:
                lines.append(f"The user wrote: {text[:_KNOWN_USER_TEXT_MAX_CHARS]}")
            break
    tool_facts = _turn_tool_facts(result_messages)
    if tool_facts:
        lines.append(f"Other tools returned this turn:\n{tool_facts}")
    return "\n".join(lines)


def _run_verifier(
    answer: str, sources: str, known: str, *, timeout_seconds: float | None = None
) -> tuple[GroundingVerdict | None, dict[str, Any] | None]:
    """One structured call to the checker model. Raises on API errors/timeouts."""
    timeout = timeout_seconds or Config.GROUNDING_CHECK_TIMEOUT_SECONDS
    model = ChatGoogleGenerativeAI(
        model=Config.GROUNDING_CHECK_MODEL,
        google_api_key=Config.GEMINI_API_KEY,
        temperature=0,
        timeout=max(timeout, GEMINI_MIN_REQUEST_DEADLINE_SECONDS),
        max_retries=0,
    )
    structured = model.with_structured_output(GroundingVerdict, include_raw=True)
    out = structured.invoke(
        GROUNDING_CHECK_PROMPT.format(known=known, sources=sources, answer=answer)
    )
    if not isinstance(out, dict):  # include_raw=True always returns a dict
        return None, None
    metadata = getattr(out["raw"], "usage_metadata", None) or {}
    details = metadata.get("input_token_details") or {}
    usage = {
        "model": Config.GROUNDING_CHECK_MODEL,
        "input_tokens": int(metadata.get("input_tokens", 0)),
        "output_tokens": int(metadata.get("output_tokens", 0)),
        "cached_input_tokens": int(details.get("cache_read", 0)),
    }
    parsed = out.get("parsed")
    return (parsed if isinstance(parsed, GroundingVerdict) else None), usage


@dataclass
class GroundingOutcome:
    """Annotations to store, the footer summary, and verifier usage."""

    annotations: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None


_UNCITED_HEADER = "UNNUMBERED (may support a claim, cannot be cited):"


def format_sources(pages: list[SourcePage], uncited: str, max_chars: int) -> str:
    """Numbered pages, each capped to a fair share of max_chars, then uncited text."""
    parts = 1 + len(pages) if uncited else len(pages)
    share = max_chars // max(parts, 1)
    blocks = [f"[{i}] {p.title} ({p.url})\n{p.text[:share]}" for i, p in enumerate(pages, 1)]
    if uncited:
        blocks.append(f"{_UNCITED_HEADER}\n{uncited[:share]}")
    return "\n\n".join(blocks)


def should_check(
    answer: str, result_messages: list[BaseMessage], stop_reason: str | None = None
) -> bool:
    """Whether this answer gets a grounding check (and a grounding_started event)."""
    if not Config.GROUNDING_CHECK_ENABLED or stop_reason or not answer.strip():
        return False
    if in_delegate_run():
        # The parent turn's answer is the one users see; a check here would
        # cost an unrecorded call
        return False
    return bool(turn_pages(result_messages) or uncited_web_text(result_messages))


def check_grounding(
    answer: str, result_messages: list[BaseMessage], stop_reason: str | None = None
) -> GroundingOutcome:
    """Every specific claim in a web-tool answer, judged against its pages.

    Fails open: any verifier error returns an empty outcome.
    """
    if not should_check(answer, result_messages, stop_reason):
        return GroundingOutcome()
    return check_grounding_pages(
        answer,
        turn_pages(result_messages),
        uncited_web_text(result_messages),
        known=known_facts(result_messages),
        max_source_chars=Config.GROUNDING_CHECK_MAX_SOURCE_CHARS,
        max_claims=Config.GROUNDING_CHECK_MAX_CLAIMS,
    )


def check_grounding_pages(
    answer: str,
    pages: list[SourcePage],
    uncited: str,
    *,
    known: str,
    max_source_chars: int,
    max_claims: int,
    timeout_seconds: float | None = None,
) -> GroundingOutcome:
    """Check an answer against given numbered pages (deep research passes its
    merged pages and larger limits, and a longer timeout). Fails open."""
    sources = format_sources(pages, uncited, max_source_chars)
    started = time.monotonic()
    timeout = timeout_seconds or Config.GROUNDING_CHECK_TIMEOUT_SECONDS
    try:
        verdict, usage = _run_verifier(answer, sources, known, timeout_seconds=timeout)
    except Exception:
        logger.warning(
            "Grounding check failed", exc_info=True, extra={"source_chars": len(sources)}
        )
        return GroundingOutcome()
    claims = (verdict.unsupported + verdict.supported) if verdict else []
    if claims:
        # The verifier skips a price now and then; an empty verdict means a
        # history/background answer, where old prices are not shop claims
        missed = missed_prices(answer, sources, claims)
        claims = [*verdict.unsupported, *missed, *verdict.supported] if verdict else claims
    annotations = validate_claims(claims, answer, pages, max_claims=max_claims)
    counts = Counter(a["verdict"] for a in annotations)
    logger.info(
        "Grounding check",
        extra={
            "verdict_counts": dict(counts),
            "source_count": len(pages),
            "source_chars": len(sources),
            "duration_ms": round((time.monotonic() - started) * 1000),
            "parsed": verdict is not None,
        },
    )
    summary = summarize(len(pages)) if annotations else None
    return GroundingOutcome(annotations=annotations, summary=summary, usage=usage)


def apply_grounding(
    answer: str,
    result_messages: list[BaseMessage],
    usage_info: dict[str, Any],
    stop_reason: str | None = None,
) -> None:
    """Check the answer and record the outcome in usage_info for the save path.

    usage_info already carries the turn's usage to save_message_to_db in both
    the batch and the stream path, so the annotations ride along with it.
    `check_grounding` is looked up on the module at call time (patchable).
    """
    outcome = check_grounding(answer, result_messages, stop_reason)
    if outcome.usage:
        usage_info["grounding_usage"] = outcome.usage
    if outcome.annotations:
        usage_info["grounding"] = {"annotations": outcome.annotations, "summary": outcome.summary}
