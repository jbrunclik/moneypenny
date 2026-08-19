"""Tests for the trigger-message construction in src/agent/executor.py."""

from src.agent.executor import _build_trigger_message


class TestBuildTriggerMessage:
    def test_scheduled_has_timestamp_prefix(self) -> None:
        msg = _build_trigger_message("scheduled")
        assert msg.startswith("[Scheduled run at ")
        assert msg.endswith("UTC]")

    def test_unknown_trigger_type_falls_back(self) -> None:
        assert _build_trigger_message("webhook") == "[Triggered: webhook]"

    def test_trigger_message_includes_extra(self) -> None:
        msg = _build_trigger_message("agent_trigger", "Focus on AAPL earnings")
        assert msg.startswith("[Triggered by another agent at ")
        assert "Message from triggering agent: Focus on AAPL earnings" in msg

    def test_trigger_message_ignores_default_continue(self) -> None:
        # "Continue" is the legacy default of trigger_agent's message arg and
        # means "no message" - it must not be echoed into the trigger message.
        assert "Message from" not in _build_trigger_message("agent_trigger", "Continue")
        assert "Message from" not in _build_trigger_message("scheduled", None)
        assert "Message from" not in _build_trigger_message("scheduled", "   ")
