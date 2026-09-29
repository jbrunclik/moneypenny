"""Unit tests for usage and tool telemetry helpers in src/agent/agent.py."""


class TestUsageTokens:
    """Tests for _usage_tokens (cache-aware usage_metadata extraction)."""

    def test_full_metadata(self) -> None:
        from src.agent.agent import _usage_tokens

        usage = {
            "input_tokens": 12_614,
            "output_tokens": 130,
            "input_token_details": {"cache_read": 9_000},
        }
        assert _usage_tokens(usage) == (12_614, 130, 9_000)

    def test_missing_details_defaults_to_zero_cache(self) -> None:
        from src.agent.agent import _usage_tokens

        assert _usage_tokens({"input_tokens": 100, "output_tokens": 5}) == (100, 5, 0)

    def test_non_dict_details_ignored(self) -> None:
        from src.agent.agent import _usage_tokens

        usage = {"input_tokens": 100, "output_tokens": 5, "input_token_details": None}
        assert _usage_tokens(usage) == (100, 5, 0)

    def test_empty_usage(self) -> None:
        from src.agent.agent import _usage_tokens

        assert _usage_tokens({}) == (0, 0, 0)


class TestToolTelemetry:
    """Tests for _tool_telemetry (round-multiplication counting)."""

    def test_counts_rounds_and_calls(self) -> None:
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        from src.agent.agent import _tool_telemetry

        # One LLM round with two tool calls, then their two results
        msgs = [
            HumanMessage(content="find bakeries", id="h1"),
            AIMessage(
                content="",
                id="ai1",
                tool_calls=[
                    {"name": "web_search", "args": {}, "id": "t1"},
                    {"name": "web_search", "args": {}, "id": "t2"},
                ],
            ),
            ToolMessage(content="r1", tool_call_id="t1", id="tm1"),
            ToolMessage(content="r2", tool_call_id="t2", id="tm2"),
            AIMessage(content="here you go", id="ai2"),  # final answer, no tools
        ]
        assert _tool_telemetry(msgs) == (1, 2)  # 1 round, 2 tool executions

    def test_sequential_rounds_counted_separately(self) -> None:
        from langchain_core.messages import AIMessage, ToolMessage

        from src.agent.agent import _tool_telemetry

        # Two separate single-search rounds (the expensive pattern)
        msgs = [
            AIMessage(
                content="", id="ai1", tool_calls=[{"name": "web_search", "args": {}, "id": "a"}]
            ),
            ToolMessage(content="r", tool_call_id="a", id="tm1"),
            AIMessage(
                content="", id="ai2", tool_calls=[{"name": "web_search", "args": {}, "id": "b"}]
            ),
            ToolMessage(content="r", tool_call_id="b", id="tm2"),
        ]
        assert _tool_telemetry(msgs) == (2, 2)  # 2 rounds, 2 calls

    def test_streaming_chunks_share_id_count_once(self) -> None:
        from langchain_core.messages import AIMessageChunk

        from src.agent.agent import _tool_telemetry

        # Two chunks of the SAME response (same id) carrying tool call deltas
        chunks = [
            AIMessageChunk(
                content="",
                id="run-1",
                tool_call_chunks=[{"name": "web_search", "args": "", "id": "t1", "index": 0}],
            ),
            AIMessageChunk(
                content="",
                id="run-1",
                tool_call_chunks=[{"name": None, "args": '{"q":1}', "id": None, "index": 0}],
            ),
        ]
        rounds, _calls = _tool_telemetry(chunks)
        assert rounds == 1  # one round despite two chunks

    def test_no_tools(self) -> None:
        from langchain_core.messages import AIMessage, HumanMessage

        from src.agent.agent import _tool_telemetry

        assert _tool_telemetry([HumanMessage(content="hi"), AIMessage(content="hello")]) == (0, 0)


class TestToolUsageDetails:
    """_tool_usage_details: tool names + error counts for turn metrics."""

    def test_names_and_errors(self) -> None:
        from langchain_core.messages import ToolMessage

        from src.agent.agent import _tool_usage_details

        msgs = [
            ToolMessage(content='{"results": []}', tool_call_id="1", name="web_search"),
            ToolMessage(content='{"error": "boom"}', tool_call_id="2", name="fetch_url"),
            ToolMessage(content="plain ok", tool_call_id="3", name="web_search"),
            ToolMessage(content="failed", tool_call_id="4", name="kv_store", status="error"),
        ]

        names, errors = _tool_usage_details(msgs)

        assert names == ["fetch_url", "kv_store", "web_search"]
        assert errors == 2

    def test_empty(self) -> None:
        from src.agent.agent import _tool_usage_details

        assert _tool_usage_details([]) == ([], 0)
