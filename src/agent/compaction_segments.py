"""Segmented running summaries for conversation compaction.

The original running summary re-summarized itself every
``CONVERSATION_COMPACTION_RESUMMARIZE_BATCH`` messages under a fixed 500-word
cap, reading only the first 500 characters of each message. Long chats went
through dozens of lossy passes: a fact-recall probe on real conversations found
the oldest parts of a 449-message chat at 0% recall.

Here each batch of messages is summarized ONCE, from full text, into its own
segment that is appended to the list. Only when the total exceeds
``CONVERSATION_COMPACTION_SUMMARY_MAX_WORDS`` are two adjacent segments merged -
always the pair that has been through the fewest passes (oldest first), so the
number of passes any message goes through grows logarithmically, not linearly.
Appending also keeps the summary's prefix byte-stable between refreshes, which
Gemini's implicit prefix caching rewards.

The summarizer and merger are injectable so the algorithm is testable without
an LLM.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.agent import compaction
from src.agent.compaction import SUMMARY_FOCUS, SUMMARY_MESSAGE_MAX_CHARS
from src.config import Config

# Earlier segments shown to the summarizer as context (not re-summarized) so a
# new segment does not repeat what is already covered.
_CONTEXT_SEGMENTS = 3

# A trailing chunk smaller than this fraction of a batch is folded into the
# previous chunk - a two-message segment is not worth its own summary call.
_MIN_TAIL_FRACTION = 0.5

# Merged segments get this share of their combined length (floored at one
# segment's budget): merging must shrink, but not all the way to one segment.
_MERGE_SHRINK = 0.6

Summarizer = Callable[[list[dict[str, Any]], list[str], int], str | None]
Merger = Callable[[str, str, int], str | None]


@dataclass(frozen=True)
class Segment:
    """Summary of one contiguous run of messages."""

    text: str
    # Exclusive end index (into the conversation history) this segment covers
    end: int
    # Summarization passes this text has been through (1 = straight from messages)
    passes: int


def _words(text: str) -> int:
    return len(text.split())


def _segment_budget() -> tuple[int, int]:
    """(words per segment, total word cap), both at least 1."""
    per_segment = max(1, Config.CONVERSATION_COMPACTION_SEGMENT_WORDS)
    cap = max(per_segment, Config.CONVERSATION_COMPACTION_SUMMARY_MAX_WORDS)
    return per_segment, cap


def plan_chunks(start: int, end: int) -> list[tuple[int, int]]:
    """Split history[start:end] into chunks to summarize, one segment each.

    Chunks are ``RESUMMARIZE_BATCH`` messages long, except that a long range
    (e.g. rebuilding an old conversation) is split into at most as many chunks
    as fit the total word cap, so it does not immediately need merging.
    """
    length = end - start
    if length <= 0:
        return []
    per_segment, cap = _segment_budget()
    batch = max(1, Config.CONVERSATION_COMPACTION_RESUMMARIZE_BATCH)
    max_chunks = max(1, cap // per_segment)
    size = max(batch, math.ceil(length / max_chunks))
    bounds = list(range(start, end, size)) + [end]
    chunks = list(zip(bounds, bounds[1:], strict=False))
    if len(chunks) > 1 and chunks[-1][1] - chunks[-1][0] < batch * _MIN_TAIL_FRACTION:
        (lo, _), (_, hi) = chunks[-2], chunks[-1]
        chunks[-2:] = [(lo, hi)]
    return chunks


def _pick_merge_pair(segments: list[Segment]) -> int:
    """Index i of the adjacent pair (i, i+1) with the fewest passes, oldest first."""
    return min(
        range(len(segments) - 1),
        key=lambda i: (max(segments[i].passes, segments[i + 1].passes), i),
    )


def _enforce_cap(segments: list[Segment], merge: Merger) -> list[Segment]:
    """Merge adjacent segments until the total fits the word cap.

    A failed merge stops merging and keeps the segments over budget - a longer
    summary is better than a lost one.
    """
    per_segment, cap = _segment_budget()
    while len(segments) > 1 and sum(_words(s.text) for s in segments) > cap:
        i = _pick_merge_pair(segments)
        a, b = segments[i], segments[i + 1]
        budget = max(per_segment, round(_MERGE_SHRINK * (_words(a.text) + _words(b.text))))
        merged = merge(a.text, b.text, budget)
        if not merged:
            break
        segments = [
            *segments[:i],
            Segment(merged, b.end, max(a.passes, b.passes) + 1),
            *segments[i + 2 :],
        ]
    return segments


def extend_segments(
    segments: list[Segment],
    history: list[dict[str, Any]],
    start: int,
    end: int,
    *,
    summarize: Summarizer | None = None,
    merge: Merger | None = None,
) -> list[Segment] | None:
    """Summarize history[start:end] into new segments appended to ``segments``.

    Returns the new segment list (input segments are kept verbatim unless the
    cap forces a merge), or None when any chunk failed to summarize - the
    caller keeps its previous state and those messages stay verbatim.
    """
    summarize = summarize or summarize_segment
    merge = merge or merge_segments
    per_segment, _cap = _segment_budget()
    result = list(segments)
    for lo, hi in plan_chunks(start, end):
        context = [s.text for s in result[-_CONTEXT_SEGMENTS:]]
        text = summarize(history[lo:hi], context, per_segment)
        if not text:
            return None
        result.append(Segment(text, hi, 1))
    return _enforce_cap(result, merge)


def render_segments(segments: list[Segment]) -> str:
    """The summary text sent to the model (and shown in the UI)."""
    return "\n\n".join(s.text for s in segments)


def max_passes(segments: list[Segment]) -> int:
    """Deepest summarization any covered message has been through."""
    return max((s.passes for s in segments), default=0)


def _transcript(messages: list[dict[str, Any]]) -> str:
    lines = []
    for m in messages:
        label = "Assistant" if m.get("role") == "assistant" else "User"
        lines.append(f"{label}: {(m.get('content') or '')[:SUMMARY_MESSAGE_MAX_CHARS]}")
    return "\n\n".join(lines)


def summarize_segment(
    messages: list[dict[str, Any]], context: list[str], max_words: int
) -> str | None:
    """Summarize one chunk of messages from full text (LLM call)."""
    context_block = ""
    if context:
        joined = "\n\n".join(context)
        context_block = (
            "Earlier parts of this conversation are already summarized as follows. "
            "Use it only as context - do not repeat it:\n"
            f"{joined}\n\n"
        )
    prompt = (
        "Summarize the following part of a conversation concisely.\n"
        f"Focus on:\n{SUMMARY_FOCUS}\n\n"
        f"Keep it under {max_words} words. Write in past tense, in the language of "
        "the conversation.\n\n"
        f"{context_block}"
        f"Messages to summarize:\n{_transcript(messages)}\n\n"
        "Summary:"
    )
    # Via the module so a single patch point (tests, e2e server) covers it
    return compaction.run_summary_model(prompt)


def merge_segments(first: str, second: str, max_words: int) -> str | None:
    """Merge two consecutive segment summaries into one (LLM call)."""
    prompt = (
        "Merge these two consecutive summaries of one conversation into a single "
        "summary. Keep specific facts - names, numbers, dates, amounts, decisions - "
        "over general description.\n"
        f"Keep it under {max_words} words. Write in past tense, in the language of "
        "the conversation.\n\n"
        f"FIRST:\n{first}\n\nSECOND:\n{second}\n\n"
        "Merged summary:"
    )
    # Via the module so a single patch point (tests, e2e server) covers it
    return compaction.run_summary_model(prompt)
