"""Tests for the delegate_task subagent tool."""

import json
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from src.agent.tools.delegate import _in_delegate, delegate_task


def _mock_chat_agent(mock_agent_class: MagicMock) -> MagicMock:
    """Wire a ChatAgent mock whose chat_batch returns the standard 4-tuple."""
    cite_call = {
        "name": "cite_sources",
        "args": {"sources": [{"title": "Example", "url": "https://example.com"}]},
        "id": "tc-1",
    }
    result_messages = [AIMessage(content="Digest of findings", tool_calls=[cite_call])]
    usage_info = {
        "input_tokens": 1200,
        "output_tokens": 300,
        "cached_input_tokens": 0,
        "tool_rounds": 2,
        "tool_call_count": 3,
    }
    instance = MagicMock()
    instance.chat_batch.return_value = ("Digest of findings", [], usage_info, result_messages)
    mock_agent_class.return_value = instance
    return instance


class TestDelegateTask:
    @patch("src.agent.agent.ChatAgent")
    def test_returns_digest_sources_and_usage(self, mock_agent_class: MagicMock) -> None:
        instance = _mock_chat_agent(mock_agent_class)

        parsed = json.loads(
            delegate_task.invoke({"task": "Find X", "expected_output": "bullet list"})
        )

        assert parsed["result"] == "Digest of findings"
        assert parsed["sources"] == [{"title": "Example", "url": "https://example.com"}]
        usage = parsed["_delegate_usage"]
        assert usage["input_tokens"] == 1200
        assert usage["output_tokens"] == 300
        assert usage["model"]
        # The subagent got the full brief including the expected output
        sent_text = instance.chat_batch.call_args.kwargs["text"]
        assert "Find X" in sent_text
        assert "bullet list" in sent_text

    @patch("src.agent.agent.ChatAgent")
    def test_subagent_runs_uncached_with_override(self, mock_agent_class: MagicMock) -> None:
        _mock_chat_agent(mock_agent_class)

        delegate_task.invoke({"task": "Find X"})

        kwargs = mock_agent_class.call_args.kwargs
        assert kwargs["enable_context_cache"] is False
        assert kwargs["system_prompt_override"]
        tool_names = {t.name for t in kwargs["tools"]}
        assert "research" in tool_names
        assert "cite_sources" in tool_names
        assert "delegate_task" not in tool_names  # no recursion

    @patch("src.agent.agent.ChatAgent")
    def test_nested_delegation_refused(self, mock_agent_class: MagicMock) -> None:
        token = _in_delegate.set(True)
        try:
            parsed = json.loads(delegate_task.invoke({"task": "Find X"}))
        finally:
            _in_delegate.reset(token)

        assert "error" in parsed
        assert parsed["retriable"] is False
        mock_agent_class.assert_not_called()

    def test_empty_task_rejected(self) -> None:
        parsed = json.loads(delegate_task.invoke({"task": "   "}))
        assert "error" in parsed

    @patch("src.agent.agent.ChatAgent")
    def test_subagent_failure_reported_and_flag_reset(self, mock_agent_class: MagicMock) -> None:
        instance = MagicMock()
        instance.chat_batch.side_effect = RuntimeError("boom")
        mock_agent_class.return_value = instance

        parsed = json.loads(delegate_task.invoke({"task": "Find X"}))

        assert "error" in parsed
        assert _in_delegate.get() is False  # flag must reset on failure
