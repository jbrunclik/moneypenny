"""Unit tests for segmented running summaries (src/agent/compaction_segments.py).

The summarizer and merger are injected, so these cover the pure algorithm:
chunk planning, append-only growth, cap enforcement by merging the
least-summarized adjacent pair, and failure handling.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.agent.compaction_segments import (
    Segment,
    extend_segments,
    max_passes,
    plan_chunks,
    render_segments,
)
from src.config import Config


def _history(n: int) -> list[dict[str, Any]]:
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"message {i}"} for i in range(n)
    ]


@pytest.fixture(autouse=True)
def segment_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_RESUMMARIZE_BATCH", 10)
    monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_SEGMENT_WORDS", 5)
    monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_SUMMARY_MAX_WORDS", 20)


def _fake_summarize(calls: list[tuple[int, int, list[str]]]):
    """Summarizer returning a 5-word text naming the message range it saw."""

    def summarize(messages: list[dict[str, Any]], context: list[str], max_words: int) -> str:
        first = messages[0]["content"].split()[-1]
        last = messages[-1]["content"].split()[-1]
        calls.append((int(first), int(last), context))
        return f"summary of {first} to {last}"

    return summarize


def _fake_merge(merges: list[tuple[str, str]]):
    def merge(a: str, b: str, max_words: int) -> str:
        merges.append((a, b))
        return "merged " + " ".join(a.split()[2:]) + " " + " ".join(b.split()[2:])

    return merge


class TestPlanChunks:
    def test_batches_of_configured_size(self) -> None:
        assert plan_chunks(0, 25) == [(0, 10), (10, 20), (20, 25)]

    def test_small_trailing_chunk_folds_into_previous(self) -> None:
        # A 2-message tail is too thin to summarize on its own
        assert plan_chunks(0, 22) == [(0, 10), (10, 22)]

    def test_long_rebuild_is_capped_to_the_segment_budget(self) -> None:
        # cap 20 / 5 words per segment -> at most 4 chunks
        chunks = plan_chunks(0, 100)
        assert len(chunks) == 4
        assert chunks[0][0] == 0 and chunks[-1][1] == 100
        assert all(a[1] == b[0] for a, b in zip(chunks, chunks[1:], strict=False))

    def test_empty_range(self) -> None:
        assert plan_chunks(5, 5) == []


class TestExtendSegments:
    def test_appends_one_segment_per_chunk(self) -> None:
        calls: list[tuple[int, int, list[str]]] = []
        segments = extend_segments(
            [], _history(20), 0, 20, summarize=_fake_summarize(calls), merge=_fake_merge([])
        )
        assert segments == [
            Segment("summary of 0 to 9", end=10, passes=1),
            Segment("summary of 10 to 19", end=20, passes=1),
        ]
        # Later chunks see earlier segments as context (not re-summarized)
        assert calls[1][2] == ["summary of 0 to 9"]

    def test_existing_segments_are_kept_verbatim(self) -> None:
        existing = [Segment("old one two three four", end=10, passes=1)]
        segments = extend_segments(
            existing, _history(20), 10, 20, summarize=_fake_summarize([]), merge=_fake_merge([])
        )
        assert segments is not None
        assert segments[0] is existing[0]
        assert segments[1].end == 20

    def test_over_cap_merges_the_least_summarized_adjacent_pair(self) -> None:
        # Four 4-word segments = 16 words; the fifth pushes past the 20-word cap
        existing = [
            Segment("a1 a2 a3 a4", end=10, passes=2),
            Segment("b1 b2 b3 b4", end=20, passes=1),
            Segment("c1 c2 c3 c4", end=30, passes=1),
            Segment("d1 d2 d3 d4", end=40, passes=1),
        ]
        merges: list[tuple[str, str]] = []
        segments = extend_segments(
            existing, _history(50), 40, 50, summarize=_fake_summarize([]), merge=_fake_merge(merges)
        )
        assert segments is not None
        # b+c (both 1 pass, oldest such pair) merged - not a (already 2 passes)
        assert merges == [("b1 b2 b3 b4", "c1 c2 c3 c4")]
        assert [s.end for s in segments] == [10, 30, 40, 50]
        assert segments[1].passes == 2
        assert sum(len(s.text.split()) for s in segments) <= 20

    def test_summarizer_failure_returns_none(self) -> None:
        def failing(messages: list[dict[str, Any]], context: list[str], max_words: int) -> None:
            return None

        assert (
            extend_segments([], _history(20), 0, 20, summarize=failing, merge=_fake_merge([]))
            is None
        )

    def test_merge_failure_keeps_segments_over_cap(self) -> None:
        existing = [Segment(" ".join(["w"] * 9), end=10, passes=1)] * 2

        def failing_merge(a: str, b: str, max_words: int) -> None:
            return None

        segments = extend_segments(
            existing, _history(30), 20, 30, summarize=_fake_summarize([]), merge=failing_merge
        )
        # Nothing lost: over budget beats dropping context
        assert segments is not None
        assert len(segments) == 3


class TestHelpers:
    def test_render_joins_segments_in_order(self) -> None:
        segments = [Segment("first", end=5, passes=1), Segment("second", end=9, passes=1)]
        assert render_segments(segments) == "first\n\nsecond"

    def test_max_passes(self) -> None:
        assert max_passes([]) == 0
        assert max_passes([Segment("a", 1, 1), Segment("b", 2, 3)]) == 3


class TestRunSummaryModel:
    """The shared summary-model call (src/agent/compaction.py)."""

    @staticmethod
    def _client(text: str | None) -> Any:
        from unittest.mock import MagicMock

        response = MagicMock()
        response.text = text
        response.candidates = [MagicMock(finish_reason="SAFETY")]
        client = MagicMock()
        client.models.generate_content.return_value = response
        return client

    def test_uses_low_thinking(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Measured on production conversations: LOW thinking kept fact recall
        (81-92% vs 74-88% at the default) at ~30% lower summarizer cost."""
        from google.genai.types import ThinkingLevel

        from src.agent import compaction

        client = self._client(" summary ")
        monkeypatch.setattr("google.genai.Client", lambda **kwargs: client)

        assert compaction.run_summary_model("prompt") == "summary"
        config = client.models.generate_content.call_args.kwargs["config"]
        assert config.thinking_config.thinking_level == ThinkingLevel.LOW

    def test_empty_response_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.agent import compaction

        monkeypatch.setattr("google.genai.Client", lambda **kwargs: self._client(None))
        assert compaction.run_summary_model("prompt") is None
