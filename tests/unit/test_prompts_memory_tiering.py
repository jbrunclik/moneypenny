"""Tests for tiered memory injection in get_user_memories_list_prompt."""

from datetime import datetime, timedelta
from unittest.mock import patch

from src.agent.prompts import get_user_memories_list_prompt
from src.config import Config
from src.db.models.dataclasses import Memory


def _memory(
    idx: int,
    category: str | None = "fact",
    protected: bool = False,
    updated_days_ago: int = 0,
) -> Memory:
    now = datetime.now()
    return Memory(
        id=f"mem-{idx}",
        user_id="user-1",
        content=f"memory content {idx}",
        category=category,
        created_at=now - timedelta(days=updated_days_ago + 1),
        updated_at=now - timedelta(days=updated_days_ago),
        protected=protected,
    )


class TestMemoryTiering:
    @patch("src.agent.prompts.db")
    def test_below_threshold_injects_all(self, mock_db) -> None:
        memories = [_memory(i) for i in range(5)]
        mock_db.list_memories.return_value = memories

        prompt = get_user_memories_list_prompt("user-1")

        for memory in memories:
            assert memory.content in prompt
        assert "more memories exist" not in prompt

    @patch("src.agent.prompts.db")
    def test_above_threshold_injects_core_and_recent(self, mock_db) -> None:
        threshold = Config.MEMORY_INJECT_FULL_MAX
        recent = Config.MEMORY_INJECT_RECENT_COUNT
        # Old facts (would only survive via core/recent rules)
        facts = [_memory(i, category="fact", updated_days_ago=100 + i) for i in range(threshold)]
        core = [
            _memory(900, category="preference", updated_days_ago=300),
            _memory(901, category="goal", updated_days_ago=300),
            _memory(902, category="fact", protected=True, updated_days_ago=300),
        ]
        fresh = [_memory(950 + i, category="fact", updated_days_ago=0) for i in range(recent)]
        mock_db.list_memories.return_value = facts + core + fresh

        prompt = get_user_memories_list_prompt("user-1")

        # Core categories and protected entries always injected
        for memory in core:
            assert memory.content in prompt
        # Most recently updated non-core entries injected
        for memory in fresh:
            assert memory.content in prompt
        # The oldest plain facts are NOT injected
        assert facts[-1].content not in prompt
        # And the model is told how to reach the rest
        assert "more memories exist" in prompt
        assert "search_memory" in prompt

    @patch("src.agent.prompts.db")
    def test_above_threshold_header_shows_shown_count(self, mock_db) -> None:
        total = Config.MEMORY_INJECT_FULL_MAX + 20
        mock_db.list_memories.return_value = [
            _memory(i, category="fact", updated_days_ago=i) for i in range(total)
        ]

        prompt = get_user_memories_list_prompt("user-1")

        assert f"of {total}/" in prompt


class TestMemoryUnicode:
    @patch("src.agent.prompts.db")
    def test_injected_memories_keep_unicode(self, mock_db) -> None:
        """Czech characters must not be \\uXXXX-escaped in the prompt.

        The model copies what it sees: ensure_ascii escapes round-tripped
        into STORED memories via update/consolidation (observed Aug 2026).
        """
        memory = _memory(1)
        memory.content = "Hodinky: stříbrné/titanový tah, zvažuje Seiko"
        mock_db.list_memories.return_value = [memory]

        prompt = get_user_memories_list_prompt("user-1")

        assert "stříbrné/titanový" in prompt
        assert "\\u0159" not in prompt


class TestDecodeEscapes:
    def test_decodes_czech_sequences(self) -> None:
        from scripts.fix_memory_unicode_escapes import decode_escapes

        poisoned = "st\\u0159\\u00edbrn\\u00e9/titanov\\u00fd tah, zva\\u017euje Seiko"
        assert decode_escapes(poisoned) == "stříbrné/titanový tah, zvažuje Seiko"

    def test_leaves_clean_text_alone(self) -> None:
        from scripts.fix_memory_unicode_escapes import decode_escapes

        clean = "stříbrné hodinky, C:\\Users\\path is not an escape"
        assert decode_escapes(clean) == clean
