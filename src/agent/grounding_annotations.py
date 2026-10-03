"""Validated grounding claims: what the verifier said, kept only where provable.

The verifier (src/agent/grounding_check.py) judges each specific claim in an
answer against the turn's numbered pages (src/agent/source_pages.py). Nothing
it returns is trusted: a quote must be in the answer, a source passage must be
in the cited page, or the claim loses its source. Spec:
docs/superpowers/specs/2026-10-03-grounding-annotations-design.md.
"""

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.agent.source_pages import SourcePage
from src.config import Config

Verdict = Literal["supported", "partial", "not_found", "contradicted"]
_PREFIX_CHARS = 32
_WITH_SOURCE: frozenset[str] = frozenset({"supported", "partial", "contradicted"})
# A bare time or time range ("10:15", "12:00–14:15"). Three or more unsupported
# ones are the answer's own timeline, which the verifier flags despite the prompt
_BARE_TIME = re.compile(r"~?\d{1,2}[:.]\d{2}(?:\s*[–—-]\s*\d{1,2}[:.]\d{2})?")
_SCHEDULE_MIN_TIMES = 3
_SPACE = re.compile(r"\s+")


class ClaimVerdict(BaseModel):
    """One specific claim in the answer and how the sources bear on it."""

    quote: str = Field(
        ..., description="The shortest phrase stating the claim, copied exactly from the ANSWER"
    )
    verdict: Verdict
    source: int | None = Field(
        default=None, description="Number of the SOURCE page, e.g. 2 for [2]"
    )
    source_quote: str | None = Field(
        default=None, description="Passage copied exactly from that page"
    )
    reason: str | None = Field(default=None, description="One sentence, in the ANSWER's language")


class GroundingVerdict(BaseModel):
    """The verifier's structured output."""

    claims: list[ClaimVerdict] = Field(default_factory=list)


def _norm(text: str) -> str:
    return _SPACE.sub(" ", text).strip().casefold()


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _passage_in_page(claim: ClaimVerdict, pages: list[SourcePage]) -> bool:
    if claim.source is None or not claim.source_quote or not 1 <= claim.source <= len(pages):
        return False
    return _norm(claim.source_quote) in _norm(pages[claim.source - 1].text)


def _annotation(
    claim: ClaimVerdict, answer: str, start: int, pages: list[SourcePage]
) -> dict[str, Any]:
    quote = claim.quote.strip()
    ann: dict[str, Any] = {
        "type": "claim",
        "verdict": claim.verdict,
        "quote": quote,
        "prefix": answer[max(0, start - _PREFIX_CHARS) : start],
    }
    cited = _passage_in_page(claim, pages)
    if claim.verdict in _WITH_SOURCE and cited:
        ann["source"] = claim.source
        ann["source_quote"] = _clip(
            claim.source_quote or "", Config.GROUNDING_CHECK_MAX_SOURCE_QUOTE_CHARS
        )
    elif claim.verdict != "supported" or claim.source is not None:
        # Unprovable passage: a claim is never shown with a source it lacks.
        # A supported claim with no number at all is backed by uncited text.
        ann["verdict"] = "not_found"
    if ann["verdict"] != "supported" and claim.reason:
        ann["reason"] = _clip(claim.reason.strip(), Config.GROUNDING_CHECK_MAX_REASON_CHARS)
    return ann


def _drop_schedule_times(anns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    times = [a for a in anns if a["verdict"] != "supported" and _BARE_TIME.fullmatch(a["quote"])]
    if len(times) < _SCHEDULE_MIN_TIMES:
        return anns
    return [a for a in anns if a not in times]


def validate_claims(
    claims: list[ClaimVerdict], answer: str, pages: list[SourcePage]
) -> list[dict[str, Any]]:
    """Annotations for the claims that can be shown, in answer order."""
    haystack = answer.casefold()
    placed: list[tuple[int, dict[str, Any]]] = []
    seen: set[str] = set()
    for claim in claims:
        quote = claim.quote.strip()
        start = haystack.find(quote.casefold()) if quote else -1
        if start < 0 or quote in seen or len(quote) > Config.GROUNDING_CHECK_MAX_QUOTE_CHARS:
            continue
        seen.add(quote)
        placed.append((start, _annotation(claim, answer, start, pages)))
        if len(placed) >= Config.GROUNDING_CHECK_MAX_CLAIMS:
            break
    placed.sort(key=lambda item: item[0])
    return _drop_schedule_times([ann for _, ann in placed])


def summarize(source_count: int) -> dict[str, Any]:
    """The footer's summary for a checked answer."""
    return {"checked": True, "source_count": source_count}


_CONTEXT_LABELS = {
    "not_found": "unsourced",
    "partial": "partly sourced",
    "contradicted": "contradicted",
}


def format_grounding_context(annotations: list[dict[str, Any]] | None) -> str | None:
    """MSG_CONTEXT entry: the claims a later turn must not repeat as fact."""
    groups: dict[str, list[str]] = {}
    for ann in annotations or []:
        label = _CONTEXT_LABELS.get(ann.get("verdict", ""))
        if not label:
            continue
        reason = (ann.get("reason") or "").replace("-->", "").strip()
        groups.setdefault(label, []).append(
            f"{ann['quote']} ({reason})" if reason else ann["quote"]
        )
    if not groups:
        return None
    text = "; ".join(f"{label}: {', '.join(items)}" for label, items in groups.items())
    return _clip(text.replace("-->", ""), Config.GROUNDING_CONTEXT_MAX_CHARS)
