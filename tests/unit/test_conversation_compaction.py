"""Unit tests for non-destructive conversation compaction.

Covers src/agent/conversation_compaction.py: threshold gating, segmented
summary persistence via kv_store, lazy refresh, legacy-state rebuild, failure
backoff, and the display status. The segment algorithm itself is covered in
test_compaction_segments.py - here ``extend_segments`` is replaced by a fake.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.agent import conversation_compaction as cc
from src.agent.compaction_segments import Segment
from src.agent.conversation_compaction import (
    SUMMARY_PREFIX,
    SUMMARY_RECALL_HINT,
    CompactionStatus,
    build_compacted_history,
    get_compaction_status,
)
from src.config import Config

NOW = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)


def _history(n: int) -> list[dict[str, Any]]:
    """Build n enriched history messages (alternating user/assistant)."""
    return [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"message {i}",
            "metadata": {"timestamp": "2024-06-15 14:30 CET"},
        }
        for i in range(n)
    ]


def _big_history(n: int, chars_each: int) -> list[dict[str, Any]]:
    """Build n enriched messages with large content bodies."""
    return [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"message {i} " + "x" * chars_each,
            "metadata": {"timestamp": "2024-06-15 14:30 CET"},
        }
        for i in range(n)
    ]


def _state(*segments: tuple[str, int, int], **extra: Any) -> str:
    """Serialized segmented state from (text, end, passes) tuples."""
    return json.dumps(
        {
            "segments": [{"text": t, "end": e, "passes": p} for t, e, p in segments],
            "covered_count": segments[-1][1] if segments else 0,
            **extra,
        }
    )


def _summary_content(text: str) -> str:
    return f"{SUMMARY_PREFIX}\n\n{text}\n\n{SUMMARY_RECALL_HINT}"


@pytest.fixture
def compaction_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic compaction thresholds for tests."""
    monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_ENABLED", True)
    monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_THRESHOLD", 10)
    monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_KEEP_RECENT", 4)
    monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_RESUMMARIZE_BATCH", 5)


@pytest.fixture
def mock_db(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Mock the kv_store-backed db used by the module."""
    db = MagicMock()
    db.kv_get.return_value = None
    monkeypatch.setattr(cc, "db", db)
    return db


@pytest.fixture(autouse=True)
def synchronous_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the (normally background) summary refresh inline for determinism."""
    monkeypatch.setattr(cc, "_spawn_refresh", lambda work: work())
    monkeypatch.setattr(cc, "_now", lambda: NOW)


class FakeExtend:
    """Stands in for extend_segments: appends one "NEW" segment, or fails."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[Segment], int, int]] = []
        self.fail = False

    def __call__(
        self, segments: list[Segment], history: list[dict[str, Any]], start: int, end: int
    ) -> list[Segment] | None:
        self.calls.append((list(segments), start, end))
        if self.fail:
            return None
        return [*segments, Segment("NEW", end, 1)]


@pytest.fixture
def fake_extend(monkeypatch: pytest.MonkeyPatch) -> FakeExtend:
    fake = FakeExtend()
    monkeypatch.setattr(cc, "extend_segments", fake)
    return fake


def _saved(mock_db: MagicMock) -> dict[str, Any]:
    _user, namespace, key, value = mock_db.kv_set.call_args.args
    assert namespace == cc.KV_NAMESPACE
    assert key == "c1"
    return json.loads(value)


class TestGating:
    def test_disabled_returns_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, mock_db: MagicMock
    ) -> None:
        monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_ENABLED", False)
        history = _history(50)
        assert build_compacted_history("u1", "c1", history) is history
        mock_db.kv_get.assert_not_called()

    def test_missing_user_or_conversation_returns_unchanged(
        self, compaction_config: None, mock_db: MagicMock
    ) -> None:
        history = _history(50)
        assert build_compacted_history(None, "c1", history) is history
        assert build_compacted_history("u1", None, history) is history

    def test_below_threshold_returns_unchanged(
        self, compaction_config: None, mock_db: MagicMock
    ) -> None:
        history = _history(10)  # == threshold, not greater
        assert build_compacted_history("u1", "c1", history) is history
        mock_db.kv_get.assert_not_called()


class TestFirstCompaction:
    def test_first_compaction_builds_segments_in_background(
        self, compaction_config: None, mock_db: MagicMock, fake_extend: FakeExtend
    ) -> None:
        """The summarizer runs OFF the request path: this turn returns the
        full history; the persisted summary serves the NEXT turn."""
        history = _history(20)  # older=16, recent=4
        result = build_compacted_history("u1", "c1", history)

        assert result is history
        assert fake_extend.calls == [([], 0, 16)]  # built from scratch
        assert _saved(mock_db) == {
            "segments": [{"text": "NEW", "end": 16, "passes": 1}],
            "covered_count": 16,
        }

        # Next turn picks up the persisted summary
        mock_db.kv_get.return_value = _state(("NEW", 16, 1))
        result2 = build_compacted_history("u1", "c1", history)
        assert result2[0]["content"] == _summary_content("NEW")
        assert result2[0]["metadata"] == {}
        assert result2[1:] == history[-4:]

    def test_failure_returns_full_history_and_backs_off(
        self, compaction_config: None, mock_db: MagicMock, fake_extend: FakeExtend
    ) -> None:
        fake_extend.fail = True
        history = _history(20)
        result = build_compacted_history("u1", "c1", history)

        # Context must not be lost: full history unchanged
        assert result is history
        saved = _saved(mock_db)
        assert saved["segments"] == []
        assert saved["failures"] == 1
        assert saved["retry_after"] == (NOW + timedelta(minutes=30)).isoformat()


class TestTokenTrigger:
    def test_token_trigger_fires_below_message_count(
        self,
        compaction_config: None,
        mock_db: MagicMock,
        fake_extend: FakeExtend,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A few huge messages compact long before the message-count threshold."""
        monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_TOKEN_THRESHOLD", 1000)
        history = _big_history(8, 3000)  # 8 msgs <= count threshold 10, ~8k est tokens

        result = build_compacted_history("u1", "c1", history)
        assert fake_extend.calls == [([], 0, 4)]  # older 4 messages summarized
        assert result is history

        mock_db.kv_get.return_value = _state(("S", 4, 1))
        result2 = build_compacted_history("u1", "c1", history)
        assert result2[0]["content"].startswith(SUMMARY_PREFIX)
        assert result2[1:] == history[-4:]

    def test_token_trigger_disabled_with_zero(
        self,
        compaction_config: None,
        mock_db: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_TOKEN_THRESHOLD", 0)
        history = _big_history(8, 30_000)
        assert build_compacted_history("u1", "c1", history) is history
        mock_db.kv_get.assert_not_called()

    def test_tail_shrinks_for_huge_recent_messages(
        self,
        compaction_config: None,
        mock_db: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When the verbatim tail alone exceeds the token threshold, it shrinks
        down to the floor so compaction actually bounds what is sent."""
        monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_KEEP_RECENT", 8)
        monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_TOKEN_THRESHOLD", 1000)
        history = _big_history(12, 3000)  # over count threshold too (12 > 10)

        mock_db.kv_get.return_value = _state(("S", 8, 1))
        result = build_compacted_history("u1", "c1", history)

        # Tail shrank from 8 to the floor of 4; older = first 8 (all covered)
        assert result[0]["content"].startswith(SUMMARY_PREFIX)
        assert result[1:] == history[-4:]

    def test_history_smaller_than_tail_floor_unchanged(
        self,
        compaction_config: None,
        mock_db: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Nothing to summarize when everything fits in the minimum tail."""
        monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_TOKEN_THRESHOLD", 1000)
        history = _big_history(4, 3000)  # over tokens, but only 4 messages
        assert build_compacted_history("u1", "c1", history) is history


class TestSegmentedSummary:
    def test_reuses_summary_without_refreshing(
        self, compaction_config: None, mock_db: MagicMock, fake_extend: FakeExtend
    ) -> None:
        # Segments cover 14; older is 16 -> uncovered middle = 2 < batch(5)
        mock_db.kv_get.return_value = _state(("A", 7, 1), ("B", 14, 1))
        history = _history(20)
        result = build_compacted_history("u1", "c1", history)

        assert fake_extend.calls == []
        mock_db.kv_set.assert_not_called()
        # [summary of both segments] + uncovered middle (2) + recent (4)
        assert result[0]["content"] == _summary_content("A\n\nB")
        assert result[1:3] == history[14:16]
        assert result[3:] == history[-4:]

    def test_appends_when_middle_grows_past_batch(
        self, compaction_config: None, mock_db: MagicMock, fake_extend: FakeExtend
    ) -> None:
        # Covers 5; older is 16 -> uncovered middle = 11 >= batch(5)
        mock_db.kv_get.return_value = _state(("OLD", 5, 1))
        history = _history(20)
        result = build_compacted_history("u1", "c1", history)

        # Only the uncovered range is summarized, existing segment kept
        assert fake_extend.calls == [([Segment("OLD", 5, 1)], 5, 16)]
        assert _saved(mock_db)["segments"] == [
            {"text": "OLD", "end": 5, "passes": 1},
            {"text": "NEW", "end": 16, "passes": 1},
        ]
        # Current turn still serves the PRIOR summary + middle (refresh is async)
        assert result[0]["content"] == _summary_content("OLD")
        assert len(result) == 1 + 11 + 4

    def test_refresh_failure_keeps_prior_segments_and_middle(
        self, compaction_config: None, mock_db: MagicMock, fake_extend: FakeExtend
    ) -> None:
        fake_extend.fail = True
        mock_db.kv_get.return_value = _state(("OLD", 5, 1))
        history = _history(20)
        result = build_compacted_history("u1", "c1", history)

        saved = _saved(mock_db)
        assert saved["segments"] == [{"text": "OLD", "end": 5, "passes": 1}]
        assert saved["failures"] == 1
        assert result[0]["content"] == _summary_content("OLD")
        assert len(result) == 1 + 11 + 4

    def test_malformed_state_is_discarded(
        self, compaction_config: None, mock_db: MagicMock, fake_extend: FakeExtend
    ) -> None:
        mock_db.kv_get.return_value = "not json{"
        history = _history(20)
        result = build_compacted_history("u1", "c1", history)

        assert fake_extend.calls == [([], 0, 16)]
        assert result is history

    def test_coverage_clamped_when_history_shrinks(
        self, compaction_config: None, mock_db: MagicMock, fake_extend: FakeExtend
    ) -> None:
        mock_db.kv_get.return_value = _state(("OLD", 999, 1))
        history = _history(20)  # older=16
        result = build_compacted_history("u1", "c1", history)

        assert fake_extend.calls == []
        assert result[0]["content"] == _summary_content("OLD")
        assert len(result) == 1 + 0 + 4


class TestLegacyState:
    def test_legacy_state_is_served_then_rebuilt_from_scratch(
        self, compaction_config: None, mock_db: MagicMock, fake_extend: FakeExtend
    ) -> None:
        """Pre-segment {summary, covered_count} keeps serving this turn, and a
        full rebuild from message text replaces it - even when the middle is
        below the batch size."""
        mock_db.kv_get.return_value = json.dumps({"summary": "LEGACY", "covered_count": 14})
        history = _history(20)
        result = build_compacted_history("u1", "c1", history)

        assert result[0]["content"] == _summary_content("LEGACY")
        assert fake_extend.calls == [([], 0, 16)]
        assert _saved(mock_db)["segments"] == [{"text": "NEW", "end": 16, "passes": 1}]

    def test_failed_rebuild_keeps_legacy_marker_and_retries(
        self, compaction_config: None, mock_db: MagicMock, fake_extend: FakeExtend
    ) -> None:
        """A failed rebuild must not lose the legacy marker - otherwise the
        lossy legacy summary would be kept forever once backoff clears."""
        fake_extend.fail = True
        mock_db.kv_get.return_value = json.dumps(
            {"summary": "LEGACY", "covered_count": 14, "generation": 5}
        )
        build_compacted_history("u1", "c1", _history(20))
        saved = mock_db.kv_set.call_args.args[3]

        # Backoff over: the next turn rebuilds from scratch again
        fake_extend.fail = False
        fake_extend.calls.clear()
        state = json.loads(saved)
        state["retry_after"] = (NOW - timedelta(minutes=1)).isoformat()
        mock_db.kv_get.return_value = json.dumps(state)
        build_compacted_history("u1", "c1", _history(20))

        assert fake_extend.calls == [([], 0, 16)]
        assert _saved(mock_db)["segments"] == [{"text": "NEW", "end": 16, "passes": 1}]

    def test_failed_rebuild_keeps_estimated_generation_for_display(
        self, compaction_config: None, mock_db: MagicMock, fake_extend: FakeExtend
    ) -> None:
        fake_extend.fail = True
        mock_db.kv_get.return_value = json.dumps({"summary": "LEGACY", "covered_count": 16})
        build_compacted_history("u1", "c1", _history(20))

        mock_db.kv_get.return_value = mock_db.kv_set.call_args.args[3]
        status = get_compaction_status("u1", "c1", _history(20))
        assert status is not None
        assert status.generation_estimated is True


class TestBackoff:
    def test_no_refresh_while_backing_off(
        self, compaction_config: None, mock_db: MagicMock, fake_extend: FakeExtend
    ) -> None:
        mock_db.kv_get.return_value = _state(
            ("OLD", 5, 1), failures=2, retry_after=(NOW + timedelta(minutes=5)).isoformat()
        )
        result = build_compacted_history("u1", "c1", _history(20))

        assert fake_extend.calls == []
        assert result[0]["content"] == _summary_content("OLD")

    def test_retries_after_backoff_and_doubles_delay(
        self, compaction_config: None, mock_db: MagicMock, fake_extend: FakeExtend
    ) -> None:
        fake_extend.fail = True
        mock_db.kv_get.return_value = _state(
            ("OLD", 5, 1), failures=2, retry_after=(NOW - timedelta(minutes=1)).isoformat()
        )
        build_compacted_history("u1", "c1", _history(20))

        saved = _saved(mock_db)
        assert saved["failures"] == 3
        assert saved["retry_after"] == (NOW + timedelta(hours=2)).isoformat()

    def test_success_clears_failures(
        self, compaction_config: None, mock_db: MagicMock, fake_extend: FakeExtend
    ) -> None:
        mock_db.kv_get.return_value = _state(
            ("OLD", 5, 1), failures=4, retry_after=(NOW - timedelta(minutes=1)).isoformat()
        )
        build_compacted_history("u1", "c1", _history(20))

        assert "failures" not in _saved(mock_db)

    def test_backoff_is_capped_at_a_day(self, compaction_config: None) -> None:
        state = cc._with_failure(cc._State(failures=20))
        assert state.retry_after == (NOW + timedelta(days=1)).isoformat()


class TestBackgroundRefresh:
    def test_inflight_refresh_is_not_duplicated(
        self,
        compaction_config: None,
        mock_db: MagicMock,
        fake_extend: FakeExtend,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """While a refresh is pending, further turns must not spawn another."""
        captured: list[Any] = []
        monkeypatch.setattr(cc, "_spawn_refresh", lambda work: captured.append(work))

        history = _history(20)
        build_compacted_history("u1", "c1", history)
        build_compacted_history("u1", "c1", history)
        assert len(captured) == 1  # second call saw the in-flight flag

        # Completing the work clears the flag and persists state
        captured[0]()
        mock_db.kv_set.assert_called_once()
        assert "c1" not in cc._inflight_refreshes


class TestCompactionStatus:
    def test_none_when_below_threshold(self, compaction_config: None, mock_db: MagicMock) -> None:
        mock_db.kv_get.return_value = _state(("S", 4, 1))
        assert get_compaction_status("u1", "c1", _history(10)) is None

    def test_none_without_summary_yet(self, compaction_config: None, mock_db: MagicMock) -> None:
        assert get_compaction_status("u1", "c1", _history(20)) is None

    def test_none_when_disabled(
        self, compaction_config: None, mock_db: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_ENABLED", False)
        mock_db.kv_get.return_value = _state(("S", 16, 1))
        assert get_compaction_status("u1", "c1", _history(20)) is None

    def test_reports_what_the_next_turn_sends(
        self, compaction_config: None, mock_db: MagicMock
    ) -> None:
        mock_db.kv_get.return_value = _state(("A", 6, 1), ("B", 12, 3))
        status = get_compaction_status("u1", "c1", _history(20))
        assert status == CompactionStatus(
            summarized_count=12,
            total_count=20,
            generation=3,  # deepest segment
            generation_estimated=False,
            summary="A\n\nB",
        )

    def test_coverage_clamped_to_older_portion(
        self, compaction_config: None, mock_db: MagicMock
    ) -> None:
        mock_db.kv_get.return_value = _state(("S", 999, 1))
        status = get_compaction_status("u1", "c1", _history(20))
        assert status is not None
        assert status.summarized_count == 16  # 20 - keep_recent(4)

    def test_legacy_state_estimates_generation(
        self, compaction_config: None, mock_db: MagicMock
    ) -> None:
        # First pass covers >= threshold+1-keep_recent (7); each later one >= batch (5)
        mock_db.kv_get.return_value = json.dumps({"summary": "S", "covered_count": 16})
        status = get_compaction_status("u1", "c1", _history(20))
        assert status is not None
        assert status.generation == 2
        assert status.generation_estimated is True

    def test_legacy_state_with_recorded_generation(
        self, compaction_config: None, mock_db: MagicMock
    ) -> None:
        mock_db.kv_get.return_value = json.dumps(
            {"summary": "S", "covered_count": 12, "generation": 3}
        )
        status = get_compaction_status("u1", "c1", _history(20))
        assert status is not None
        assert (status.generation, status.generation_estimated) == (3, False)

    def test_never_schedules_a_refresh(
        self, compaction_config: None, mock_db: MagicMock, fake_extend: FakeExtend
    ) -> None:
        mock_db.kv_get.return_value = _state(("S", 1, 1))
        get_compaction_status("u1", "c1", _history(20))
        assert fake_extend.calls == []
        mock_db.kv_set.assert_not_called()
