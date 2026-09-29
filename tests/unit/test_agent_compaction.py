"""Tests for destructive autonomous-agent compaction (src/agent/compaction.py).

Agent conversations reuse the segmented summaries of regular chats: the prior
summary message is kept as the first segment instead of being re-folded into
a single new summary on every compaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.agent import compaction
from src.api.schemas.common import MessageRole
from src.config import Config
from src.db.models.dataclasses import Agent, Message

SUMMARY_MARKER = "[Previous conversation summary]\n\n"


def _agent() -> Agent:
    return Agent(
        id="agent-1",
        user_id="user-1",
        conversation_id="conv-1",
        name="VWCE watcher",
        description="Watches the ETF price",
        system_prompt=None,
        schedule=None,
        timezone="UTC",
        enabled=True,
        tool_permissions=None,
        model="gemini-3-flash-preview",
        created_at=datetime(2024, 1, 1),
        updated_at=datetime(2024, 1, 1),
        last_run_at=None,
        next_run_at=None,
    )


def _message(i: int, content: str | None = None, role: MessageRole | None = None) -> Message:
    return Message(
        id=f"m{i}",
        conversation_id="conv-1",
        role=role or (MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT),
        content=content if content is not None else f"message {i}",
        created_at=datetime(2024, 1, 1, 0, 0, i),
    )


@pytest.fixture
def agent_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "AGENT_COMPACTION_THRESHOLD", 10)
    monkeypatch.setattr(Config, "AGENT_COMPACTION_KEEP_RECENT", 4)
    monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_RESUMMARIZE_BATCH", 5)
    monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_SEGMENT_WORDS", 50)
    monkeypatch.setattr(Config, "CONVERSATION_COMPACTION_SUMMARY_MAX_WORDS", 500)


@pytest.fixture
def mock_db(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    db = MagicMock()
    db.get_agent_message_count.return_value = 99
    db.compact_agent_conversation.return_value = 3
    monkeypatch.setattr(compaction, "db", db)
    return db


class TestCompactConversation:
    def test_prior_summary_kept_as_first_segment(
        self, agent_config: None, mock_db: MagicMock
    ) -> None:
        prompts: list[str] = []
        mock_db.get_messages.return_value = [
            _message(0, SUMMARY_MARKER + "PRIOR SUMMARY TEXT", MessageRole.USER),
            *[_message(i) for i in range(1, 16)],
        ]

        def model(prompt: str) -> str:
            prompts.append(prompt)
            return f"NEW SEGMENT {len(prompts)}"

        with patch.object(compaction, "run_summary_model", side_effect=model):
            assert compaction.compact_conversation(_agent()) is True

        summary = mock_db.compact_agent_conversation.call_args.args[1]
        # Prior summary verbatim first, then segments for messages 1..11
        assert summary.startswith("PRIOR SUMMARY TEXT\n\nNEW SEGMENT 1")
        assert SUMMARY_MARKER not in summary
        # The prior summary is context for new segments, never re-summarized
        assert all("message 0" not in p for p in prompts)
        assert "PRIOR SUMMARY TEXT" in prompts[0]
        assert mock_db.compact_agent_conversation.call_args.kwargs["keep_recent"] == 4

    def test_agent_labels_and_identity_in_prompt(
        self, agent_config: None, mock_db: MagicMock
    ) -> None:
        mock_db.get_messages.return_value = [_message(i) for i in range(12)]
        with patch.object(compaction, "run_summary_model", return_value="S") as model:
            compaction.compact_conversation(_agent())

        first_chunk = model.call_args_list[0].args[0]
        assert "Trigger: message 0" in first_chunk
        assert "Agent: message 1" in first_chunk
        assert "VWCE watcher" in first_chunk

    def test_summarizer_failure_skips_compaction(
        self, agent_config: None, mock_db: MagicMock
    ) -> None:
        """Compaction deletes messages - without a real summary it must not run
        (it used to delete them behind a placeholder "history was compacted")."""
        mock_db.get_messages.return_value = [_message(i) for i in range(12)]
        with patch.object(compaction, "run_summary_model", return_value=None):
            assert compaction.compact_conversation(_agent()) is False

        mock_db.compact_agent_conversation.assert_not_called()

    def test_full_text_reaches_the_summarizer(self, agent_config: None, mock_db: MagicMock) -> None:
        long_text = "x" * 3000 + " TAIL-MARKER"
        mock_db.get_messages.return_value = [
            _message(0, long_text),
            *[_message(i) for i in range(1, 12)],
        ]
        seen: list[Any] = []
        with patch.object(
            compaction, "run_summary_model", side_effect=lambda p: seen.append(p) or "S"
        ):
            compaction.compact_conversation(_agent())

        assert any("TAIL-MARKER" in p for p in seen)
