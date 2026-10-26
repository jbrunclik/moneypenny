"""Unit tests for should_continue() routing in src/agent/graph.py."""


class TestSmartRouting:
    """Tests for should_continue() smart routing in graph.py.

    Verifies that extract-only tool calls (set_conversation_title) route to "end" while
    real tool calls - including manage_memory - route to "tools".
    """

    def test_metadata_only_routes_to_end(self) -> None:
        """set_conversation_title-only tool calls should route to 'end'."""
        from langchain_core.messages import AIMessage

        from src.agent.graph import AgentState, should_continue

        state: AgentState = {
            "messages": [
                AIMessage(
                    content="Answer.",
                    tool_calls=[
                        {"name": "set_conversation_title", "args": {"title": "🦀 Rust"}, "id": "1"}
                    ],
                )
            ]
        }
        assert should_continue(state) == "end"

    def test_manage_memory_routes_to_tools_even_with_text(self) -> None:
        """manage_memory must execute: it performs the write and reports it.

        Regression: manage_memory used to be treated as metadata, so a response
        with text plus a memory write short-circuited to "end" and the tool
        never ran. The write was replayed afterwards from the tool call args,
        which meant the model never learned whether it succeeded.
        """
        from langchain_core.messages import AIMessage

        from src.agent.graph import AgentState, should_continue

        state: AgentState = {
            "messages": [
                AIMessage(
                    content="Noted.",
                    tool_calls=[
                        {
                            "name": "manage_memory",
                            "args": {"operations": [{"action": "add", "content": "x"}]},
                            "id": "1",
                        }
                    ],
                )
            ]
        }
        assert should_continue(state) == "tools"

    def test_citation_plus_memory_routes_to_tools(self) -> None:
        """A batch containing manage_memory must still reach the tool node."""
        from langchain_core.messages import AIMessage

        from src.agent.graph import AgentState, should_continue

        state: AgentState = {
            "messages": [
                AIMessage(
                    content="Done.",
                    tool_calls=[
                        {"name": "set_conversation_title", "args": {"title": "🦀 Rust"}, "id": "1"},
                        {"name": "manage_memory", "args": {"operations": []}, "id": "2"},
                    ],
                )
            ]
        }
        assert should_continue(state) == "tools"

    def test_real_tool_routes_to_tools(self) -> None:
        """Non-metadata tool calls should route to 'tools'."""
        from langchain_core.messages import AIMessage

        from src.agent.graph import AgentState, should_continue

        state: AgentState = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "web_search", "args": {"query": "test"}, "id": "1"}],
                )
            ]
        }
        assert should_continue(state) == "tools"

    def test_mixed_real_and_metadata_routes_to_tools(self) -> None:
        """Mix of real + metadata tool calls should route to 'tools'."""
        from langchain_core.messages import AIMessage

        from src.agent.graph import AgentState, should_continue

        state: AgentState = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "web_search", "args": {"query": "test"}, "id": "1"},
                        {"name": "set_conversation_title", "args": {"title": "🦀 Rust"}, "id": "2"},
                    ],
                )
            ]
        }
        assert should_continue(state) == "tools"

    def test_no_tool_calls_routes_to_end(self) -> None:
        """Message without tool calls should route to 'end'."""
        from langchain_core.messages import AIMessage

        from src.agent.graph import AgentState, should_continue

        state: AgentState = {"messages": [AIMessage(content="Just text.")]}
        assert should_continue(state) == "end"
