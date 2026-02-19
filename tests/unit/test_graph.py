"""Unit tests for graph improvements: self-correction, planning, and checkpointing."""

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agent.graph import (
    AgentState,
    check_tool_results,
    compile_graph,
    create_chat_graph,
    get_graph_config,
    should_continue,
    should_plan,
)

# ============ should_continue Tests ============


class TestShouldContinue:
    """Tests for should_continue routing."""

    def test_routes_to_tools_on_tool_calls(self) -> None:
        """AI message with tool calls should route to 'tools'."""
        state: AgentState = {
            "messages": [
                AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "1"}])
            ],
            "tool_retries": 0,
            "plan": "",
        }
        assert should_continue(state) == "tools"

    def test_routes_to_end_on_no_tool_calls(self) -> None:
        """AI message without tool calls should route to 'end'."""
        state: AgentState = {
            "messages": [AIMessage(content="Hello!")],
            "tool_retries": 0,
            "plan": "",
        }
        assert should_continue(state) == "end"

    def test_routes_to_end_on_metadata_only_tools(self) -> None:
        """AI message with only metadata tool calls should route to 'end'."""
        state: AgentState = {
            "messages": [
                AIMessage(
                    content="Here's my answer.",
                    tool_calls=[
                        {"name": "cite_sources", "args": {"sources": []}, "id": "1"},
                        {"name": "manage_memory", "args": {"operations": []}, "id": "2"},
                    ],
                )
            ],
            "tool_retries": 0,
            "plan": "",
        }
        assert should_continue(state) == "end"

    def test_routes_to_tools_on_mixed_tool_calls(self) -> None:
        """AI message with mixed tool calls (metadata + regular) should route to 'tools'."""
        state: AgentState = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "cite_sources", "args": {}, "id": "1"},
                        {"name": "web_search", "args": {"query": "test"}, "id": "2"},
                    ],
                )
            ],
            "tool_retries": 0,
            "plan": "",
        }
        assert should_continue(state) == "tools"


# ============ check_tool_results Tests ============


class TestCheckToolResults:
    """Tests for check_tool_results self-correction node."""

    def test_detects_error_status(self) -> None:
        """ToolMessage with status='error' should trigger retry guidance."""
        error_msg = ToolMessage(content="Connection refused", tool_call_id="1")
        error_msg.status = "error"  # type: ignore[attr-defined]
        state: AgentState = {
            "messages": [
                AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "1"}]),
                error_msg,
            ],
            "tool_retries": 0,
            "plan": "",
        }
        result = check_tool_results(state)
        assert result["tool_retries"] == 1
        assert "messages" in result
        guidance = result["messages"][0]
        assert isinstance(guidance, SystemMessage)
        assert "failed" in guidance.content.lower()
        assert "different approach" in guidance.content.lower()

    def test_detects_error_content_patterns(self) -> None:
        """ToolMessage with error text patterns should trigger retry guidance."""
        state: AgentState = {
            "messages": [
                AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "1"}]),
                ToolMessage(content="Error: API returned 500", tool_call_id="1"),
            ],
            "tool_retries": 0,
            "plan": "",
        }
        result = check_tool_results(state)
        assert result["tool_retries"] == 1
        assert "messages" in result

    def test_resets_on_success(self) -> None:
        """Successful tool results should reset retry counter."""
        state: AgentState = {
            "messages": [
                AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "1"}]),
                ToolMessage(content="Search results: ...", tool_call_id="1"),
            ],
            "tool_retries": 2,
            "plan": "",
        }
        result = check_tool_results(state)
        assert result["tool_retries"] == 0
        assert "messages" not in result

    def test_gives_up_after_max_retries(self) -> None:
        """After max retries, should provide give-up guidance."""
        state: AgentState = {
            "messages": [
                AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "1"}]),
                ToolMessage(content="Error: API returned 500", tool_call_id="1"),
            ],
            "tool_retries": 2,  # Already at max (default is 2)
            "plan": "",
        }
        result = check_tool_results(state)
        assert result["tool_retries"] == 3
        assert "messages" in result
        guidance = result["messages"][0]
        assert isinstance(guidance, SystemMessage)
        assert "failed after multiple retries" in guidance.content.lower()

    def test_scans_only_latest_tool_messages(self) -> None:
        """Should only scan ToolMessages until the triggering AIMessage."""
        # Old error in earlier round, success in latest round
        state: AgentState = {
            "messages": [
                AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "1"}]),
                ToolMessage(content="Error: something failed", tool_call_id="1"),
                AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "2"}]),
                ToolMessage(content="Success: found results", tool_call_id="2"),
            ],
            "tool_retries": 1,
            "plan": "",
        }
        result = check_tool_results(state)
        assert result["tool_retries"] == 0  # Reset, because latest tools succeeded


# ============ should_plan Tests ============


class TestShouldPlan:
    """Tests for should_plan routing."""

    def test_short_message_skips(self) -> None:
        """Short messages should skip planning (fast path, no LLM call)."""
        state: AgentState = {
            "messages": [HumanMessage(content="Hello there!")],
            "tool_retries": 0,
            "plan": "",
        }
        assert should_plan(state) == "chat"

    @patch("src.agent.graph.Config")
    def test_disabled_planning_skips(self, mock_config: MagicMock) -> None:
        """When planning is disabled, should always skip."""
        mock_config.AGENT_PLANNING_ENABLED = False
        mock_config.AGENT_PLANNING_MIN_LENGTH = 200
        state: AgentState = {
            "messages": [HumanMessage(content="x" * 500)],
            "tool_retries": 0,
            "plan": "",
        }
        assert should_plan(state) == "chat"

    def test_existing_plan_skips(self) -> None:
        """If plan already exists, should skip planning."""
        state: AgentState = {
            "messages": [HumanMessage(content="x" * 500)],
            "tool_retries": 0,
            "plan": "Existing plan",
        }
        assert should_plan(state) == "chat"

    @patch("src.agent.graph.ChatGoogleGenerativeAI")
    def test_llm_returns_plan(self, mock_llm_class: MagicMock) -> None:
        """When LLM classifier returns PLAN, should route to plan."""
        mock_response = MagicMock()
        mock_response.content = "PLAN"
        mock_instance = MagicMock()
        mock_instance.invoke.return_value = mock_response
        mock_llm_class.return_value = mock_instance

        complex_msg = "x" * 250  # Over min length threshold
        state: AgentState = {
            "messages": [HumanMessage(content=complex_msg)],
            "tool_retries": 0,
            "plan": "",
        }
        assert should_plan(state) == "plan"

    @patch("src.agent.graph.ChatGoogleGenerativeAI")
    def test_llm_returns_chat(self, mock_llm_class: MagicMock) -> None:
        """When LLM classifier returns CHAT, should route to chat."""
        mock_response = MagicMock()
        mock_response.content = "CHAT"
        mock_instance = MagicMock()
        mock_instance.invoke.return_value = mock_response
        mock_llm_class.return_value = mock_instance

        long_msg = "x" * 250  # Over min length threshold
        state: AgentState = {
            "messages": [HumanMessage(content=long_msg)],
            "tool_retries": 0,
            "plan": "",
        }
        assert should_plan(state) == "chat"

    @patch("src.agent.graph.ChatGoogleGenerativeAI")
    def test_llm_error_falls_back_to_chat(self, mock_llm_class: MagicMock) -> None:
        """On LLM error, should fall back to chat."""
        mock_instance = MagicMock()
        mock_instance.invoke.side_effect = RuntimeError("API error")
        mock_llm_class.return_value = mock_instance

        long_msg = "x" * 250
        state: AgentState = {
            "messages": [HumanMessage(content=long_msg)],
            "tool_retries": 0,
            "plan": "",
        }
        assert should_plan(state) == "chat"

    def test_no_human_message_skips(self) -> None:
        """No HumanMessage in state should skip planning."""
        state: AgentState = {
            "messages": [SystemMessage(content="System prompt")],
            "tool_retries": 0,
            "plan": "",
        }
        assert should_plan(state) == "chat"


# ============ Checkpointing Tests ============


class TestCheckpointing:
    """Tests for graph compilation with checkpointing."""

    @patch("src.agent.graph.Config")
    def test_checkpointer_passed_to_compile(self, mock_config: MagicMock) -> None:
        """Graph should be compiled with checkpointer when enabled."""
        mock_config.AGENT_CHECKPOINTING_ENABLED = True
        mock_graph = MagicMock()
        compile_graph(mock_graph)
        mock_graph.compile.assert_called_once()
        call_kwargs = mock_graph.compile.call_args[1]
        assert "checkpointer" in call_kwargs
        assert call_kwargs["checkpointer"] is not None

    @patch("src.agent.graph.Config")
    def test_no_checkpointer_when_disabled(self, mock_config: MagicMock) -> None:
        """Graph should be compiled without checkpointer when disabled."""
        mock_config.AGENT_CHECKPOINTING_ENABLED = False
        mock_graph = MagicMock()
        compile_graph(mock_graph)
        mock_graph.compile.assert_called_once_with()

    @patch("src.agent.graph.Config")
    def test_config_with_thread_id(self, mock_config: MagicMock) -> None:
        """Config should include thread_id when checkpointing is enabled."""
        mock_config.AGENT_CHECKPOINTING_ENABLED = True
        config = get_graph_config("conv-123")
        assert config["configurable"]["thread_id"] == "conv-123"
        assert "recursion_limit" in config

    @patch("src.agent.graph.Config")
    def test_config_without_conversation_id(self, mock_config: MagicMock) -> None:
        """Config without conversation_id should still have recursion_limit."""
        mock_config.AGENT_CHECKPOINTING_ENABLED = True
        config = get_graph_config(None)
        assert "recursion_limit" in config
        assert "configurable" not in config

    @patch("src.agent.graph.Config")
    def test_config_when_disabled(self, mock_config: MagicMock) -> None:
        """Config when checkpointing disabled should just have recursion_limit."""
        mock_config.AGENT_CHECKPOINTING_ENABLED = False
        config = get_graph_config("conv-123")
        assert "recursion_limit" in config
        assert "configurable" not in config


# ============ Graph Structure Tests ============


class TestGraphStructure:
    """Tests for graph construction."""

    @patch("src.agent.graph.create_chat_model")
    @patch("src.agent.graph.create_tool_node")
    @patch("src.agent.graph.TOOLS", [MagicMock(name="mock_tool")])
    def test_graph_has_check_tool_results_node(
        self, mock_create_tool_node: MagicMock, mock_model: MagicMock
    ) -> None:
        """Graph with tools should include check_tool_results node."""
        mock_model.return_value = MagicMock()
        mock_create_tool_node.return_value = lambda state: state
        graph = create_chat_graph("test-model")
        node_names = set(graph.nodes.keys())
        assert "check_tool_results" in node_names
        assert "plan" in node_names
        assert "chat" in node_names
        assert "tools" in node_names

    @patch("src.agent.graph.create_chat_model")
    def test_simple_graph_has_no_extra_nodes(self, mock_model: MagicMock) -> None:
        """Graph without tools should be simple chat -> END."""
        mock_model.return_value = MagicMock()
        graph = create_chat_graph("test-model", with_tools=False)
        node_names = set(graph.nodes.keys())
        assert "chat" in node_names
        assert "tools" not in node_names
        assert "check_tool_results" not in node_names
        assert "plan" not in node_names


# ============ chat_node Plan Injection Tests ============


class TestChatNodePlanInjection:
    """Tests for plan injection in chat_node."""

    @patch("src.agent.graph.with_retry")
    def test_injects_plan_into_messages(self, mock_retry: MagicMock) -> None:
        """When plan exists, chat_node should inject it as SystemMessage."""
        from src.agent.graph import chat_node

        mock_model = MagicMock()
        mock_response = AIMessage(content="Response with plan context")
        mock_retry.return_value = lambda msgs: mock_response

        state: AgentState = {
            "messages": [
                SystemMessage(content="System prompt"),
                HumanMessage(content="Do complex task"),
            ],
            "tool_retries": 0,
            "plan": "1. Search web\n2. Analyze results",
        }

        result = chat_node(state, mock_model)

        # Plan should be cleared after use
        assert result.get("plan") == ""
        # Response should be in messages
        assert mock_response in result["messages"]

        assert result["messages"] == [mock_response]

    @patch("src.agent.graph.with_retry")
    def test_no_injection_without_plan(self, mock_retry: MagicMock) -> None:
        """Without plan, chat_node should not modify messages."""
        from src.agent.graph import chat_node

        mock_model = MagicMock()
        mock_response = AIMessage(content="Normal response")
        mock_retry.return_value = lambda msgs: mock_response

        state: AgentState = {
            "messages": [
                SystemMessage(content="System prompt"),
                HumanMessage(content="Simple question"),
            ],
            "tool_retries": 0,
            "plan": "",
        }

        result = chat_node(state, mock_model)

        # No plan key in result (plan was empty)
        assert "plan" not in result
        assert result["messages"] == [mock_response]
