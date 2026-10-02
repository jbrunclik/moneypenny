"""Post-answer grounding check.

The Sep 2026 conversation sweep's most common correction was stale or invented
specifics, and prompt rules (GROUNDING_DIRECTIVE, the unverified-specifics rule)
were measured to have no effect. So after a turn that used web tools, a cheap
model compares the answer with what the turn actually read, and the specifics
the sources don't support are marked in place (src/agent/grounding_markers.py). See
docs/superpowers/specs/2026-10-02-grounding-check-design.md.
"""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from src.agent.content import (
    detect_response_language,
    extract_text_content,
    strip_echoed_msg_context,
)
from src.agent.grounding_markers import mark_unverified
from src.agent.prompt_texts.grounding import GROUNDING_CHECK_PROMPT
from src.agent.tools.delegate import in_delegate_run
from src.config import Config
from src.constants import GEMINI_MIN_REQUEST_DEADLINE_SECONDS
from src.utils.logging import get_logger

logger = get_logger(__name__)

WEB_TOOL_NAMES = frozenset({"research", "web_search", "fetch_url", "browser"})

_SOURCE_SEPARATOR = "\n\n---\n\n"


class UnverifiedItem(BaseModel):
    """One specific in the answer that the sources don't support."""

    text: str = Field(..., description="The specific exactly as written in the answer")
    # No "hours"/"place" kinds: they let the verifier misfile the answer's own
    # timeline and well-known towns as unsupported (prod, Oct 2026)
    kind: Literal["business", "event", "price", "hours_or_date", "contact", "other"] = "other"


class GroundingVerdict(BaseModel):
    """The verifier's structured output."""

    unsupported: list[UnverifiedItem] = Field(default_factory=list)
    false_claims: list[str] = Field(
        default_factory=list,
        description="Sentences, exactly as written, where the answer claims it verified "
        "something the sources do not support",
    )


@dataclass
class GroundingResult:
    """Items and false claims to mark, item kinds (logged only), and verifier usage."""

    items: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    false_claims: list[str] = field(default_factory=list)
    usage: dict[str, Any] | None = None


def collect_web_sources(result_messages: list[BaseMessage], max_chars: int) -> str:
    """Text of the turn's successful web tool results, newest first, capped.

    Later results usually matter most (a research round after a search), so the
    cap is filled from the end of the turn backwards; the kept parts are then
    returned in their original order.
    """
    parts: list[str] = []
    total = 0
    for msg in reversed(result_messages):
        if not isinstance(msg, ToolMessage) or msg.name not in WEB_TOOL_NAMES:
            continue
        if msg.status == "error":
            continue
        text = extract_text_content(msg.content).strip()
        remaining = max_chars - total
        if not text or remaining <= 0:
            continue
        parts.append(text[:remaining])
        total += len(parts[-1])
    return _SOURCE_SEPARATOR.join(reversed(parts))


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
    answer: str, sources: str, known: str
) -> tuple[GroundingVerdict | None, dict[str, Any] | None]:
    """One structured call to the checker model. Raises on API errors/timeouts."""
    model = ChatGoogleGenerativeAI(
        model=Config.GROUNDING_CHECK_MODEL,
        google_api_key=Config.GEMINI_API_KEY,
        temperature=0,
        timeout=max(Config.GROUNDING_CHECK_TIMEOUT_SECONDS, GEMINI_MIN_REQUEST_DEADLINE_SECONDS),
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


# A bare time or time range ("10:15", "12:00–14:15"). Three or more flagged
# ones are the answer's own timeline, which the verifier sometimes flags
# despite the prompt (live probe, Oct 2026: 8 of 8 items were plan times);
# a single flagged range is more likely real opening hours
_BARE_TIME = re.compile(r"~?\d{1,2}[:.]\d{2}(?:\s*[–—-]\s*\d{1,2}[:.]\d{2})?")
_SCHEDULE_MIN_TIMES = 3


def _drop_schedule_times(items: list[str], kinds: list[str]) -> tuple[list[str], list[str]]:
    """Drop bare-time items when there are enough of them to be a timeline."""
    is_time = [bool(_BARE_TIME.fullmatch(item)) for item in items]
    if sum(is_time) < _SCHEDULE_MIN_TIMES:
        return items, kinds
    kept = [i for i, t in enumerate(is_time) if not t]
    return [items[i] for i in kept], [kinds[i] for i in kept]


def _literal(texts: list[str], answer: str, cap: int, max_chars: int | None = None) -> list[int]:
    """Indexes of texts that appear literally in the answer, de-duplicated, capped."""
    haystack = answer.casefold()
    kept: list[int] = []
    seen: set[str] = set()
    for index, raw in enumerate(texts):
        text = raw.strip()
        if not text or text in seen or text.casefold() not in haystack:
            continue
        if max_chars is not None and len(text) > max_chars:
            continue
        seen.add(text)
        kept.append(index)
        if len(kept) >= cap:
            break
    return kept


def _keep(verdict: GroundingVerdict | None, answer: str) -> tuple[list[str], list[str], list[str]]:
    """(items, kinds, false_claims) that may be marked in the answer."""
    if verdict is None:
        return [], [], []
    texts = [item.text for item in verdict.unsupported]
    idx = _literal(
        texts, answer, Config.GROUNDING_CHECK_MAX_ITEMS, Config.GROUNDING_CHECK_MAX_ITEM_CHARS
    )
    claims = verdict.false_claims
    kept_claims = _literal(claims, answer, Config.GROUNDING_CHECK_MAX_FALSE_CLAIMS)
    items, kinds = _drop_schedule_times(
        [texts[i].strip() for i in idx], [verdict.unsupported[i].kind for i in idx]
    )
    return items, kinds, [claims[i].strip() for i in kept_claims]


def find_unverified(
    answer: str, result_messages: list[BaseMessage], stop_reason: str | None = None
) -> GroundingResult:
    """Specifics in a web-tool turn's answer that its sources don't support.

    Fails open: any verifier error returns an empty result, so the answer goes
    out unchanged.
    """
    if not Config.GROUNDING_CHECK_ENABLED or stop_reason or not answer.strip():
        return GroundingResult()
    if in_delegate_run():
        # The parent turn's answer is the one users see; a check here would
        # cost an unrecorded call and put markers into the digest
        return GroundingResult()
    sources = collect_web_sources(result_messages, Config.GROUNDING_CHECK_MAX_SOURCE_CHARS)
    if not sources:
        return GroundingResult()
    started = time.monotonic()
    try:
        verdict, usage = _run_verifier(answer, sources, known_facts(result_messages))
    except Exception:
        logger.warning(
            "Grounding check failed", exc_info=True, extra={"source_chars": len(sources)}
        )
        return GroundingResult()
    items, kinds, false_claims = _keep(verdict, answer)
    logger.info(
        "Grounding check",
        extra={
            "flagged_count": len(items),
            "false_claim_count": len(false_claims),
            "kinds": kinds,
            "source_chars": len(sources),
            "duration_ms": round((time.monotonic() - started) * 1000),
            "parsed": verdict is not None,
        },
    )
    return GroundingResult(items=items, kinds=kinds, false_claims=false_claims, usage=usage)


def apply_grounding(
    answer: str,
    result_messages: list[BaseMessage],
    usage_info: dict[str, Any],
    stop_reason: str | None = None,
) -> str:
    """The answer with unverified specifics marked in place; records verifier usage.

    Called by ChatAgent for both batch and streamed turns so evals see exactly
    what users see. `find_unverified` is looked up on the module at call time,
    which keeps it patchable in tests.
    """
    result = find_unverified(answer, result_messages, stop_reason)
    if result.usage:
        usage_info["grounding_usage"] = result.usage
    language = detect_response_language(answer)
    return mark_unverified(answer, result.items, result.false_claims, language)
