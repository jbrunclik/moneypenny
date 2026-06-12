"""Unit tests for non-destructive conversation compaction.

Covers src/agent/conversation_compaction.py: threshold gating, running-summary
persistence via kv_store, lazy re-summarization, and failure fallbacks.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.agent import conversation_compaction as cc
from src.agent.conversation_compaction import (
    SUMMARY_PREFIX,
    build_compacted_history,
)
from src.config import Config


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
    def test_first_compaction_refreshes_in_background(
        self, compaction_config: None, mock_db: MagicMock
    ) -> None:
        """The summarizer runs OFF the request path: this turn returns the
        full history; the persisted summary serves the NEXT turn."""
        history = _history(20)  # older=16, recent=4
        with patch.object(cc, "summarize_messages", return_value="SUMMARY") as mock_sum:
            result = build_compacted_history("u1", "c1", history)

        mock_sum.assert_called_once()
        assert result is history  # current turn unchanged

        # Next turn picks up the freshly persisted summary
        mock_db.kv_get.return_value = json.dumps({"summary": "SUMMARY", "covered_count": 16})
        with patch.object(cc, "summarize_messages") as mock_sum2:
            result2 = build_compacted_history("u1", "c1", history)
        mock_sum2.assert_not_called()
        assert result2[0]["content"] == f"{SUMMARY_PREFIX}\n\nSUMMARY"
        assert result2[0]["metadata"] == {}
        assert result2[1:] == history[-4:]

    def test_persists_state_with_full_older_coverage(
        self, compaction_config: None, mock_db: MagicMock
    ) -> None:
        history = _history(20)  # older=16
        with patch.object(cc, "summarize_messages", return_value="SUMMARY"):
            build_compacted_history("u1", "c1", history)

        mock_db.kv_set.assert_called_once()
        _user, namespace, key, value = mock_db.kv_set.call_args.args
        assert namespace == cc.KV_NAMESPACE
        assert key == "c1"
        assert json.loads(value) == {"summary": "SUMMARY", "covered_count": 16}

    def test_no_prior_summary_and_failure_returns_full_history(
        self, compaction_config: None, mock_db: MagicMock
    ) -> None:
        history = _history(20)
        with patch.object(cc, "summarize_messages", return_value=None):
            result = build_compacted_history("u1", "c1", history)

        # Context must not be lost: fall back to the full history unchanged
        assert result is history
        mock_db.kv_set.assert_not_called()


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


class TestTokenTrigger:
    def test_token_trigger_fires_below_message_count(
        self,
        compaction_config: None,
        mock_db: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A few huge messages compact long before the message-count threshold."""
        monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_TOKEN_THRESHOLD", 1000)
        history = _big_history(8, 3000)  # 8 msgs <= count threshold 10, ~8k est tokens

        with patch.object(cc, "summarize_messages", return_value="SUMMARY") as mock_sum:
            result = build_compacted_history("u1", "c1", history)

        mock_sum.assert_called_once()  # older 4 messages went to the summarizer
        assert result is history  # first turn unchanged (summary not ready yet)

        # Next turn uses the persisted summary: 4 older summarized, 4 recent kept
        mock_db.kv_get.return_value = json.dumps({"summary": "SUMMARY", "covered_count": 4})
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

        mock_db.kv_get.return_value = json.dumps({"summary": "SUMMARY", "covered_count": 8})
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


class TestRunningSummary:
    def test_reuses_summary_without_resummarizing(
        self, compaction_config: None, mock_db: MagicMock
    ) -> None:
        # Prior summary covers 14 messages; older is 16 -> uncovered middle = 2 < batch(5)
        mock_db.kv_get.return_value = json.dumps({"summary": "OLD", "covered_count": 14})
        history = _history(20)  # older=16, recent=4
        with patch.object(cc, "summarize_messages") as mock_sum:
            result = build_compacted_history("u1", "c1", history)

        mock_sum.assert_not_called()
        mock_db.kv_set.assert_not_called()
        # [summary] + uncovered middle (2) + recent (4)
        assert result[0]["content"] == f"{SUMMARY_PREFIX}\n\nOLD"
        assert len(result) == 1 + 2 + 4
        assert result[1:3] == history[14:16]
        assert result[3:] == history[-4:]

    def test_resummarizes_when_middle_grows_past_batch(
        self, compaction_config: None, mock_db: MagicMock
    ) -> None:
        # Prior covers 5; older is 16 -> uncovered middle = 11 >= batch(5)
        mock_db.kv_get.return_value = json.dumps({"summary": "OLD", "covered_count": 5})
        history = _history(20)
        with patch.object(cc, "summarize_messages", return_value="NEW") as mock_sum:
            result = build_compacted_history("u1", "c1", history)

        # Prior summary is folded in
        assert mock_sum.call_args.kwargs["prior_summary"] == "OLD"
        # Only the uncovered middle (indices 5..15) is summarized
        summarized = mock_sum.call_args.args[0]
        assert len(summarized) == 11
        # New state covers the full older portion
        _u, _ns, _k, value = mock_db.kv_set.call_args.args
        assert json.loads(value) == {"summary": "NEW", "covered_count": 16}
        # Current turn still serves the PRIOR summary + middle (refresh is async)
        assert result[0]["content"] == f"{SUMMARY_PREFIX}\n\nOLD"
        assert len(result) == 1 + 11 + 4

    def test_resummarize_failure_keeps_prior_summary_and_middle(
        self, compaction_config: None, mock_db: MagicMock
    ) -> None:
        mock_db.kv_get.return_value = json.dumps({"summary": "OLD", "covered_count": 5})
        history = _history(20)
        with patch.object(cc, "summarize_messages", return_value=None):
            result = build_compacted_history("u1", "c1", history)

        # State left untouched; prior summary + uncovered middle + recent returned
        mock_db.kv_set.assert_not_called()
        assert result[0]["content"] == f"{SUMMARY_PREFIX}\n\nOLD"
        assert len(result) == 1 + 11 + 4

    def test_malformed_state_is_discarded(
        self, compaction_config: None, mock_db: MagicMock
    ) -> None:
        mock_db.kv_get.return_value = "not json{"
        history = _history(20)
        with patch.object(cc, "summarize_messages", return_value="FRESH") as mock_sum:
            result = build_compacted_history("u1", "c1", history)

        # Treated as no prior summary -> full re-summarize (in background)
        mock_sum.assert_called_once()
        assert mock_sum.call_args.kwargs["prior_summary"] is None
        # Current turn sends full history; FRESH serves the next turn
        assert result is history

    def test_coverage_clamped_when_history_shrinks(
        self, compaction_config: None, mock_db: MagicMock
    ) -> None:
        # covered_count exceeds older length (history was trimmed in the UI)
        mock_db.kv_get.return_value = json.dumps({"summary": "OLD", "covered_count": 999})
        history = _history(20)  # older=16
        with patch.object(cc, "summarize_messages", return_value="NEW") as mock_sum:
            result = build_compacted_history("u1", "c1", history)

        # Clamped coverage -> uncovered middle empty -> no growth -> reuse prior
        mock_sum.assert_not_called()
        assert result[0]["content"] == f"{SUMMARY_PREFIX}\n\nOLD"
        assert len(result) == 1 + 0 + 4


class TestBackgroundRefresh:
    def test_inflight_refresh_is_not_duplicated(
        self, compaction_config: None, mock_db: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """While a refresh is pending, further turns must not spawn another."""
        captured: list[Any] = []
        monkeypatch.setattr(cc, "_spawn_refresh", lambda work: captured.append(work))

        history = _history(20)
        with patch.object(cc, "summarize_messages", return_value="S"):
            build_compacted_history("u1", "c1", history)
            build_compacted_history("u1", "c1", history)

            assert len(captured) == 1  # second call saw the in-flight flag

            # Completing the work clears the flag and persists state
            captured[0]()

        mock_db.kv_set.assert_called_once()
        assert "c1" not in cc._inflight_refreshes
