"""Unit tests for conversation title resolution in the save pipeline.

Covers both the first-exchange auto-generation (existing behavior) and the
agent-driven retitle via the set_conversation_title extract-only tool.
"""

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from src.api.helpers.chat_save import _resolve_title_update
from src.config import Config


def _retitle_messages(title: str) -> list[AIMessage]:
    return [
        AIMessage(
            content="Switching topics.",
            tool_calls=[{"name": "set_conversation_title", "args": {"title": title}, "id": "1"}],
        )
    ]


def _conv(
    title: str,
    is_sports: bool = False,
    is_language: bool = False,
    is_planning: bool = False,
) -> MagicMock:
    conv = MagicMock()
    conv.title = title
    conv.is_sports = is_sports
    conv.is_language = is_language
    conv.is_planning = is_planning
    return conv


class TestResolveTitleUpdate:
    def test_default_title_uses_auto_generation(self) -> None:
        """First exchange keeps the existing generate_title flow."""
        with (
            patch("src.api.helpers.chat_save.db") as mock_db,
            patch("src.api.helpers.chat_save.generate_title", return_value="🐍 Python Help"),
        ):
            mock_db.get_conversation.return_value = _conv(Config.DEFAULT_CONVERSATION_TITLE)
            result = _resolve_title_update("c1", "u1", "hi", "hello", [])
        assert result == "🐍 Python Help"
        mock_db.update_conversation.assert_called_once_with("c1", "u1", title="🐍 Python Help")

    def test_agent_retitle_updates_stale_title(self) -> None:
        """A set_conversation_title call on a non-default title is applied."""
        with (
            patch("src.api.helpers.chat_save.db") as mock_db,
            patch("src.api.helpers.chat_save.generate_title") as mock_gen,
        ):
            mock_db.get_conversation.return_value = _conv("🐍 Python Help")
            result = _resolve_title_update(
                "c1", "u1", "hi", "hello", _retitle_messages("🦀 Rust Ownership")
            )
        assert result == "🦀 Rust Ownership"
        mock_db.update_conversation.assert_called_once_with("c1", "u1", title="🦀 Rust Ownership")
        mock_gen.assert_not_called()

    def test_auto_generation_takes_precedence_over_agent_retitle(self) -> None:
        """On the first exchange the auto-generated title wins over the tool."""
        with (
            patch("src.api.helpers.chat_save.db") as mock_db,
            patch("src.api.helpers.chat_save.generate_title", return_value="🐍 Python Help"),
        ):
            mock_db.get_conversation.return_value = _conv(Config.DEFAULT_CONVERSATION_TITLE)
            result = _resolve_title_update(
                "c1", "u1", "hi", "hello", _retitle_messages("🦀 Rust Ownership")
            )
        assert result == "🐍 Python Help"

    def test_unchanged_title_is_not_written(self) -> None:
        """Retitling to the current title is a no-op (no DB write, no event)."""
        with patch("src.api.helpers.chat_save.db") as mock_db:
            mock_db.get_conversation.return_value = _conv("🦀 Rust Ownership")
            result = _resolve_title_update(
                "c1", "u1", "hi", "hello", _retitle_messages("🦀 Rust Ownership")
            )
        assert result is None
        mock_db.update_conversation.assert_not_called()

    def test_no_tool_call_is_noop(self) -> None:
        with patch("src.api.helpers.chat_save.db") as mock_db:
            mock_db.get_conversation.return_value = _conv("🐍 Python Help")
            result = _resolve_title_update("c1", "u1", "hi", "hello", [])
        assert result is None
        mock_db.update_conversation.assert_not_called()

    def test_program_conversations_are_never_retitled(self) -> None:
        """Sports/language program conversations keep their titles."""
        with patch("src.api.helpers.chat_save.db") as mock_db:
            for conv in (
                _conv("🏃 Running Program", is_sports=True),
                _conv("🇪🇸 Spanish", is_language=True),
                _conv("📋 Planner", is_planning=True),
            ):
                mock_db.get_conversation.return_value = conv
                result = _resolve_title_update(
                    "c1", "u1", "hi", "hello", _retitle_messages("🦀 Rust Ownership")
                )
                assert result is None
        mock_db.update_conversation.assert_not_called()

    def test_retitle_failure_never_raises(self) -> None:
        """A DB failure during retitle must not abort the message save."""
        with patch("src.api.helpers.chat_save.db") as mock_db:
            mock_db.get_conversation.return_value = _conv("🐍 Python Help")
            mock_db.update_conversation.side_effect = RuntimeError("db down")
            result = _resolve_title_update(
                "c1", "u1", "hi", "hello", _retitle_messages("🦀 Rust Ownership")
            )
        assert result is None
