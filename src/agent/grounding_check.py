"""Post-answer grounding check.

The Sep 2026 conversation sweep's most common correction was stale or invented
specifics, and prompt rules (GROUNDING_DIRECTIVE, the unverified-specifics rule)
were measured to have no effect. So after a turn that used web tools, a cheap
model compares the answer with what the turn actually read, and a one-line note
names the specifics the sources don't support. See
docs/superpowers/specs/2026-10-02-grounding-check-design.md.
"""

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
from src.agent.prompt_texts.grounding import GROUNDING_CHECK_PROMPT
from src.config import Config
from src.constants import GEMINI_MIN_REQUEST_DEADLINE_SECONDS
from src.utils.logging import get_logger

logger = get_logger(__name__)

WEB_TOOL_NAMES = frozenset({"research", "web_search", "fetch_url", "browser"})

_SOURCE_SEPARATOR = "\n\n---\n\n"

_NOTE_TEMPLATES = {
    "cs": "_Neověřeno ve zdrojích, které jsem teď četl: {items}._",
    "en": "_Not confirmed in the sources I read for this answer: {items}._",
}


class UnverifiedItem(BaseModel):
    """One specific in the answer that the sources don't support."""

    text: str = Field(..., description="The specific exactly as written in the answer")
    kind: Literal["shop", "place", "price", "hours", "date", "figure", "other"] = "other"


class GroundingVerdict(BaseModel):
    """The verifier's structured output."""

    unsupported: list[UnverifiedItem] = Field(default_factory=list)


@dataclass
class GroundingResult:
    """Items to name in the note, their kinds (logged only), and verifier usage."""

    items: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
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


def append_unverified_note(answer: str, items: list[str], language: str | None) -> str:
    """The answer plus a one-line note naming unverified items (none: unchanged)."""
    if not items:
        return answer
    template = _NOTE_TEMPLATES.get(language or "", _NOTE_TEMPLATES["en"])
    return f"{answer.rstrip()}\n\n{template.format(items=', '.join(items))}"


# The user's message is context, not evidence of a web fact; a cap keeps a
# pasted wall of text from crowding the sources out of the verifier call
_KNOWN_USER_TEXT_MAX_CHARS = 4000


def _now() -> datetime:
    """Seam for tests (patching time globally also shifts date.today())."""
    return datetime.now().astimezone()


def known_facts(result_messages: list[BaseMessage]) -> str:
    """What the answer may state without a web source: today's date and the
    user's own message (the system prompt gives the model the date, so a
    verifier without it flags "today" as unsupported)."""
    lines = [f"Today is {_now().strftime('%A %Y-%m-%d %H:%M %Z')}."]
    for msg in reversed(result_messages):
        if isinstance(msg, HumanMessage):
            text = strip_echoed_msg_context(extract_text_content(msg.content)).strip()
            if text:
                lines.append(f"The user wrote: {text[:_KNOWN_USER_TEXT_MAX_CHARS]}")
            break
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


def _keep_items(verdict: GroundingVerdict | None, answer: str) -> tuple[list[str], list[str]]:
    """Items that literally appear in the answer, de-duplicated, capped."""
    if verdict is None:
        return [], []
    haystack = answer.casefold()
    items: list[str] = []
    kinds: list[str] = []
    for item in verdict.unsupported:
        text = item.text.strip()
        if not text or text.casefold() not in haystack or text in items:
            continue
        items.append(text)
        kinds.append(item.kind)
        if len(items) >= Config.GROUNDING_CHECK_MAX_ITEMS:
            break
    return items, kinds


def find_unverified(
    answer: str, result_messages: list[BaseMessage], stop_reason: str | None = None
) -> GroundingResult:
    """Specifics in a web-tool turn's answer that its sources don't support.

    Fails open: any verifier error returns an empty result, so the answer goes
    out unchanged.
    """
    if not Config.GROUNDING_CHECK_ENABLED or stop_reason or not answer.strip():
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
    items, kinds = _keep_items(verdict, answer)
    logger.info(
        "Grounding check",
        extra={
            "flagged_count": len(items),
            "kinds": kinds,
            "source_chars": len(sources),
            "duration_ms": round((time.monotonic() - started) * 1000),
            "parsed": verdict is not None,
        },
    )
    return GroundingResult(items=items, kinds=kinds, usage=usage)


def apply_grounding(
    answer: str,
    result_messages: list[BaseMessage],
    usage_info: dict[str, Any],
    stop_reason: str | None = None,
) -> str:
    """The answer with an unverified-specifics note if needed; records verifier usage.

    Called by ChatAgent for both batch and streamed turns so evals see exactly
    what users see. `find_unverified` is looked up on the module at call time,
    which keeps it patchable in tests.
    """
    result = find_unverified(answer, result_messages, stop_reason)
    if result.usage:
        usage_info["grounding_usage"] = result.usage
    return append_unverified_note(answer, result.items, detect_response_language(answer))
