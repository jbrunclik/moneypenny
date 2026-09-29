"""Unit tests for ChatAgent streaming event handling (src/agent/agent.py)."""


class TestStreamingMsgContextHandling:
    """Tests for MSG_CONTEXT block handling during streaming.

    These tests verify that echoed MSG_CONTEXT blocks are stripped correctly
    when they appear in streaming chunks, including multi-chunk scenarios.
    Note: METADATA block handling has been removed (metadata is now extracted
    via tool calls, not text blocks).
    """

    def _process_chunks(self, chunks: list[str]) -> tuple[str, list[str], bool]:
        """Simulate the MSG_CONTEXT chunk processing logic from stream_chat_events.

        This handles cross-chunk boundary scenarios where markers like
        <!-- MSG_CONTEXT: or --> are split across chunks.

        Args:
            chunks: List of text content chunks

        Returns:
            Tuple of (full_response, yielded_tokens, had_msg_context)
        """
        full_response = ""
        yielded_tokens: list[str] = []
        in_msg_context = False
        had_msg_context = False

        msg_context_marker = "<!-- MSG_CONTEXT:"
        end_marker = "-->"

        # Carryover buffer for cross-chunk marker detection
        carryover = ""

        for chunk in chunks:
            # Prepend carryover from previous chunk for cross-chunk marker detection
            text_content = carryover + chunk
            carryover = ""

            # Handle MSG_CONTEXT blocks (echoed history context)
            if in_msg_context:
                if end_marker in text_content:
                    end_pos = text_content.find(end_marker)
                    text_content = text_content[end_pos + 3 :].lstrip()
                    in_msg_context = False
                    if not text_content:
                        continue
                else:
                    for i in range(len(end_marker) - 1, 0, -1):
                        if text_content.endswith(end_marker[:i]):
                            carryover = end_marker[:i]
                            break
                    continue

            # Check for MSG_CONTEXT marker
            if msg_context_marker in text_content:
                had_msg_context = True
                marker_pos = text_content.find(msg_context_marker)
                end_pos = text_content.find(end_marker, marker_pos)
                if end_pos != -1:
                    before = text_content[:marker_pos]
                    after = text_content[end_pos + 3 :]
                    text_content = (before + after).strip()
                else:
                    content_after_marker = text_content[marker_pos:]
                    for i in range(len(end_marker) - 1, 0, -1):
                        if content_after_marker.endswith(end_marker[:i]):
                            carryover = end_marker[:i]
                            break
                    text_content = text_content[:marker_pos].rstrip()
                    in_msg_context = True
                if not text_content:
                    continue
            elif not in_msg_context:
                for i in range(len(msg_context_marker) - 1, 0, -1):
                    partial = msg_context_marker[:i]
                    if text_content.endswith(partial):
                        carryover = partial
                        text_content = text_content[:-i]
                        break

            full_response += text_content
            if text_content:
                yielded_tokens.append(text_content)

        # Handle any remaining carryover
        if carryover and not in_msg_context:
            full_response += carryover
            yielded_tokens.append(carryover)

        return full_response, yielded_tokens, had_msg_context

    def test_msg_context_single_chunk_stripped(self) -> None:
        """MSG_CONTEXT in a single chunk should be completely stripped."""
        chunks = ['<!-- MSG_CONTEXT: {"timestamp":"2024-01-01"} -->Hello world']
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert "MSG_CONTEXT" not in full_response
        assert "timestamp" not in full_response
        assert "Hello world" in full_response
        assert had_ctx is True

    def test_msg_context_multi_chunk_stripped(self) -> None:
        """MSG_CONTEXT spanning multiple chunks should be stripped."""
        chunks = [
            '<!-- MSG_CONTEXT: {"timestamp":',
            '"2024-01-01","relative_time":"1 hour ago"} ',
            "--> Here is the response.",
        ]
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert "MSG_CONTEXT" not in full_response
        assert "timestamp" not in full_response
        assert "Here is the response" in full_response
        assert had_ctx is True

    def test_msg_context_at_start_content_preserved(self) -> None:
        """Content after MSG_CONTEXT block should be preserved."""
        chunks = [
            "<!-- MSG_CONTEXT: {} -->",
            "This is the actual response content.",
        ]
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert "This is the actual response content" in full_response
        assert had_ctx is True
        joined_tokens = "".join(tokens)
        assert "actual response" in joined_tokens

    def test_no_metadata_blocks(self) -> None:
        """Response without any metadata blocks should yield all content."""
        chunks = ["Just a simple", " response with ", "no metadata."]
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert full_response == "Just a simple response with no metadata."
        assert had_ctx is False
        joined_tokens = "".join(tokens)
        assert "Just a simple" in joined_tokens

    def test_msg_context_marker_split_across_chunks(self) -> None:
        """MSG_CONTEXT marker split across chunk boundary."""
        chunks = ["Hello <!-- MSG_", "CONTEXT: {} --> world"]
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert "Hello" in full_response
        assert "world" in full_response
        assert "MSG_CONTEXT" not in full_response
        assert had_ctx is True

    def test_msg_context_end_marker_split_across_chunks(self) -> None:
        """MSG_CONTEXT end marker (-->) split across chunk boundary."""
        chunks = ['<!-- MSG_CONTEXT: {"key":"value"} -', "-> The response."]
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert "The response" in full_response
        assert "MSG_CONTEXT" not in full_response
        assert had_ctx is True

    def test_content_immediately_after_msg_context_end(self) -> None:
        """Content immediately after --> of MSG_CONTEXT (no space)."""
        chunks = ["<!-- MSG_CONTEXT: {} -->Response starts here."]
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert "Response starts here" in full_response
        assert "MSG_CONTEXT" not in full_response

    def test_empty_chunks_between_markers(self) -> None:
        """Empty or whitespace-only chunks within metadata block."""
        chunks = ["<!-- MSG_CONTEXT:", " ", '{"key": "value"}', "", " --> Content"]
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert "Content" in full_response
        assert "MSG_CONTEXT" not in full_response
        assert had_ctx is True

    def test_multiple_msg_context_blocks(self) -> None:
        """Multiple MSG_CONTEXT blocks (shouldn't happen but handle gracefully)."""
        chunks = ['<!-- MSG_CONTEXT: {"a":1} --> First ', '<!-- MSG_CONTEXT: {"b":2} --> Second']
        full_response, tokens, had_ctx = self._process_chunks(chunks)

        assert "First" in full_response
        assert "Second" in full_response
        assert "MSG_CONTEXT" not in full_response
        assert had_ctx is True


class TestStreamNodeFiltering:
    """Tests for langgraph_node-based filtering in streaming methods.

    Verifies that only AIMessageChunks from the "chat" node are yielded as tokens,
    while chunks from planning/classifier nodes are filtered out. Usage metadata
    from all nodes is still tracked for cost accounting.
    """

    def _simulate_stream_chat_events(self, events: list[tuple]) -> tuple[list[dict], dict | None]:
        """Simulate stream_chat_events processing of raw graph.stream events.

        Extracts the node-filtering logic to test it in isolation without
        needing a real LangGraph graph or LLM.

        Args:
            events: List of (message_chunk, metadata_dict) tuples

        Returns:
            Tuple of (yielded_events, final_event)
        """
        from langchain_core.messages import AIMessageChunk, ToolMessage

        from src.agent.graph import CHAT_NODE_NAME

        yielded_events: list[dict] = []
        full_response = ""
        tool_results: list[dict] = []
        total_input_tokens = 0
        total_output_tokens = 0
        chunk_count = 0

        for event in events:
            if isinstance(event, tuple) and len(event) >= 1:
                message_chunk = event[0]
                event_meta = event[1] if len(event) >= 2 and isinstance(event[1], dict) else {}
                source_node = event_meta.get("langgraph_node", "")

                if isinstance(message_chunk, ToolMessage):
                    tool_results.append({"type": "tool", "content": message_chunk.content})
                    continue

                if isinstance(message_chunk, AIMessageChunk):
                    chunk_count += 1
                    if hasattr(message_chunk, "usage_metadata") and message_chunk.usage_metadata:
                        usage = message_chunk.usage_metadata
                        if isinstance(usage, dict):
                            total_input_tokens += usage.get("input_tokens", 0)
                            total_output_tokens += usage.get("output_tokens", 0)

                    # Filter non-chat node output
                    if source_node and source_node != CHAT_NODE_NAME:
                        continue

                    if message_chunk.tool_calls or message_chunk.tool_call_chunks:
                        continue
                    if message_chunk.content:
                        content = (
                            message_chunk.content
                            if isinstance(message_chunk.content, str)
                            else str(message_chunk.content)
                        )
                        if content:
                            full_response += content
                            yielded_events.append({"type": "token", "text": content})

        final_event = {
            "type": "final",
            "content": full_response,
            "tool_results": tool_results,
            "usage_info": {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
            },
        }
        return yielded_events, final_event

    def test_non_chat_node_output_filtered(self) -> None:
        """AIMessageChunks from any non-chat graph node must not yield tokens.

        Uses a synthetic 'plan' node name (the real plan node was removed in
        Aug 2026); the filter applies to any auxiliary node.
        """
        from langchain_core.messages import AIMessageChunk

        events = [
            (AIMessageChunk(content="Step 1: Search the web\n"), {"langgraph_node": "plan"}),
            (AIMessageChunk(content="Step 2: Summarize results\n"), {"langgraph_node": "plan"}),
        ]
        yielded, final = self._simulate_stream_chat_events(events)

        assert len(yielded) == 0
        assert final is not None
        assert final["content"] == ""

    def test_classifier_output_filtered(self) -> None:
        """Classifier output ('PLAN'/'CHAT') from __start__ should not leak."""
        from langchain_core.messages import AIMessageChunk

        events = [
            (AIMessageChunk(content="PLAN"), {"langgraph_node": "__start__"}),
        ]
        yielded, final = self._simulate_stream_chat_events(events)

        assert len(yielded) == 0
        assert "PLAN" not in final["content"]

    def test_chat_node_output_passes_through(self) -> None:
        """AIMessageChunks from 'chat' node should yield token events."""
        from langchain_core.messages import AIMessageChunk

        events = [
            (AIMessageChunk(content="Hello "), {"langgraph_node": "chat"}),
            (AIMessageChunk(content="world!"), {"langgraph_node": "chat"}),
        ]
        yielded, final = self._simulate_stream_chat_events(events)

        assert len(yielded) == 2
        assert yielded[0]["text"] == "Hello "
        assert yielded[1]["text"] == "world!"
        assert final["content"] == "Hello world!"

    def test_tool_messages_unaffected(self) -> None:
        """ToolMessages from 'tools' node should still be captured."""
        from langchain_core.messages import ToolMessage

        events = [
            (
                ToolMessage(content='{"result": "data"}', tool_call_id="tc1"),
                {"langgraph_node": "tools"},
            ),
        ]
        yielded, final = self._simulate_stream_chat_events(events)

        assert len(yielded) == 0  # ToolMessages don't yield token events
        assert len(final["tool_results"]) == 1
        assert final["tool_results"][0]["content"] == '{"result": "data"}'

    def test_usage_tracked_from_all_nodes(self) -> None:
        """Usage metadata should be tracked from ALL nodes, not just chat."""
        from langchain_core.messages import AIMessageChunk

        plan_chunk = AIMessageChunk(content="Plan step")
        plan_chunk.usage_metadata = {"input_tokens": 100, "output_tokens": 20}

        chat_chunk = AIMessageChunk(content="Response")
        chat_chunk.usage_metadata = {"input_tokens": 500, "output_tokens": 80}

        events = [
            (plan_chunk, {"langgraph_node": "plan"}),
            (chat_chunk, {"langgraph_node": "chat"}),
        ]
        yielded, final = self._simulate_stream_chat_events(events)

        # Only chat content should be yielded
        assert len(yielded) == 1
        assert yielded[0]["text"] == "Response"
        # But usage from BOTH nodes should be tracked
        assert final["usage_info"]["input_tokens"] == 600
        assert final["usage_info"]["output_tokens"] == 100

    def test_missing_metadata_falls_through(self) -> None:
        """Events with empty metadata should be processed normally (defensive)."""
        from langchain_core.messages import AIMessageChunk

        events = [
            (AIMessageChunk(content="Fallback content"), {}),
        ]
        yielded, final = self._simulate_stream_chat_events(events)

        # Empty source_node means no filtering — content passes through
        assert len(yielded) == 1
        assert yielded[0]["text"] == "Fallback content"
        assert final["content"] == "Fallback content"


class TestToolEventCallIdKeying:
    """tool_start/tool_end events are keyed by tool_call_id, not tool name.

    Keying by name collapsed two parallel calls to the same tool into one
    tool_start, and the first result cleared the indicator while the second
    call was still running.
    """

    def _run_stream(self, events: list) -> list[dict]:
        """Drive the real stream_chat_events with a mocked graph."""
        from unittest.mock import MagicMock

        from src.agent.agent import ChatAgent

        agent = ChatAgent.__new__(ChatAgent)
        agent.graph = MagicMock()
        # stream_mode=["messages", "custom"] yields (mode, payload) pairs
        agent.graph.stream.return_value = iter(("messages", event) for event in events)
        agent._build_messages = MagicMock(return_value=[])  # type: ignore[method-assign]
        return list(agent.stream_chat_events(text="hi"))

    def test_parallel_calls_to_same_tool_emit_separate_events(self) -> None:
        """Two parallel web_search calls → two tool_start and two tool_end."""
        from langchain_core.messages import AIMessageChunk, ToolMessage

        chunk = AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "name": "web_search",
                    "args": "",
                    "id": "c1",
                    "index": 0,
                    "type": "tool_call_chunk",
                },
                {
                    "name": "web_search",
                    "args": "",
                    "id": "c2",
                    "index": 1,
                    "type": "tool_call_chunk",
                },
            ],
        )
        events = [
            (chunk, {"langgraph_node": "chat"}),
            (
                ToolMessage(content='{"r": 1}', tool_call_id="c1", name="web_search"),
                {"langgraph_node": "tools"},
            ),
            (
                ToolMessage(content='{"r": 2}', tool_call_id="c2", name="web_search"),
                {"langgraph_node": "tools"},
            ),
            (AIMessageChunk(content="Done"), {"langgraph_node": "chat"}),
        ]

        emitted = self._run_stream(events)
        starts = [e for e in emitted if e["type"] == "tool_start"]
        ends = [e for e in emitted if e["type"] == "tool_end"]

        assert len(starts) == 2
        assert all(e["tool"] == "web_search" for e in starts)
        assert len(ends) == 2
        assert all(e["tool"] == "web_search" for e in ends)

    def test_tool_end_only_after_matching_call_id(self) -> None:
        """A result for one call must not clear the other pending call."""
        from langchain_core.messages import AIMessageChunk, ToolMessage

        chunk = AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "name": "web_search",
                    "args": "",
                    "id": "c1",
                    "index": 0,
                    "type": "tool_call_chunk",
                },
                {
                    "name": "web_search",
                    "args": "",
                    "id": "c2",
                    "index": 1,
                    "type": "tool_call_chunk",
                },
            ],
        )
        events = [
            (chunk, {"langgraph_node": "chat"}),
            (
                ToolMessage(content='{"r": 1}', tool_call_id="c1", name="web_search"),
                {"langgraph_node": "tools"},
            ),
        ]

        emitted = self._run_stream(events)
        ends = [e for e in emitted if e["type"] == "tool_end"]
        assert len(ends) == 1
