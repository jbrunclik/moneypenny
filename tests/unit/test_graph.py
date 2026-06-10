"""Unit tests for graph improvements: self-correction, planning, and checkpointing."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph

from src.agent.graph import (
    AgentState,
    check_tool_results,
    compile_graph,
    create_chat_graph,
    create_tool_node,
    get_graph_config,
    should_continue,
    should_plan,
)


def _compile_tool_graph(tools: list[Any], is_autonomous: bool = False) -> Any:
    """Compile a minimal graph around create_tool_node, as production does."""
    graph: StateGraph[AgentState] = StateGraph(AgentState)
    graph.add_node("tools", create_tool_node(tools, is_autonomous=is_autonomous))
    graph.set_entry_point("tools")
    graph.add_edge("tools", END)
    return graph.compile()


def _tool_call_state(tool_calls: list[dict[str, Any]]) -> AgentState:
    """Build an AgentState whose last message requests the given tool calls."""
    return {
        "messages": [AIMessage(content="", tool_calls=tool_calls)],
        "tool_retries": 0,
        "plan": "",
    }


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

    def test_routes_to_end_on_metadata_only_tools_with_text(self) -> None:
        """AI message with text + metadata-only tool calls should route to 'end'."""
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

    def test_routes_to_tools_on_metadata_only_without_text(self) -> None:
        """AI message with metadata-only tool calls but NO text should route to 'tools'.

        This ensures the LLM gets another turn to produce a text response,
        preventing empty messages (e.g. manage_memory-only calls).
        """
        state: AgentState = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "manage_memory", "args": {"operations": []}, "id": "1"},
                    ],
                )
            ],
            "tool_retries": 0,
            "plan": "",
        }
        assert should_continue(state) == "tools"

    def test_routes_to_tools_on_metadata_only_with_thinking_only(self) -> None:
        """AI message with thinking content but no text should route to 'tools'.

        Gemini thinking models may produce thinking parts but no text alongside
        metadata tools. The thinking parts have no extractable text content.
        """
        state: AgentState = {
            "messages": [
                AIMessage(
                    content=[{"type": "thinking", "thinking": "Let me save this..."}],
                    tool_calls=[
                        {"name": "manage_memory", "args": {"operations": []}, "id": "1"},
                    ],
                )
            ],
            "tool_retries": 0,
            "plan": "",
        }
        assert should_continue(state) == "tools"

    def test_routes_to_end_on_metadata_with_gemini_text_content(self) -> None:
        """AI message with Gemini list-format text + metadata tools should route to 'end'."""
        state: AgentState = {
            "messages": [
                AIMessage(
                    content=[{"type": "text", "text": "Here is my response."}],
                    tool_calls=[
                        {"name": "cite_sources", "args": {"sources": []}, "id": "1"},
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

    def test_detects_json_error_envelope(self) -> None:
        """ToolMessage with a JSON {"error": ...} envelope should trigger retry guidance.

        This is the envelope every tool in src/agent/tools returns on failure.
        """
        state: AgentState = {
            "messages": [
                AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "1"}]),
                ToolMessage(content='{"error": "API returned 500"}', tool_call_id="1"),
            ],
            "tool_retries": 0,
            "plan": "",
        }
        result = check_tool_results(state)
        assert result["tool_retries"] == 1
        assert "messages" in result
        assert "API returned 500" in result["messages"][0].content

    def test_ignores_error_words_in_legitimate_content(self) -> None:
        """Plain content merely *mentioning* errors must not trigger guidance.

        The old substring matching ("Error:", "failed" in the first 50 chars)
        false-positived on legitimate tool output, e.g. a fetched page that
        describes a failure.
        """
        state: AgentState = {
            "messages": [
                AIMessage(content="", tool_calls=[{"name": "fetch_url", "args": {}, "id": "1"}]),
                ToolMessage(
                    content="Login failed errors: how to fix Error: 500 pages (blog post)",
                    tool_call_id="1",
                ),
            ],
            "tool_retries": 1,
            "plan": "",
        }
        result = check_tool_results(state)
        assert result["tool_retries"] == 0
        assert "messages" not in result

    def test_ignores_json_without_error_key(self) -> None:
        """A JSON tool result whose 'error' key is absent/falsy is a success."""
        state: AgentState = {
            "messages": [
                AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "1"}]),
                ToolMessage(content='{"results": [{"title": "ok"}]}', tool_call_id="1"),
            ],
            "tool_retries": 1,
            "plan": "",
        }
        result = check_tool_results(state)
        assert result["tool_retries"] == 0
        assert "messages" not in result

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
                ToolMessage(content='{"error": "API returned 500"}', tool_call_id="1"),
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

        complex_msg = "x" * 500  # Over min length threshold
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

        long_msg = "x" * 500  # Over min length threshold
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

        long_msg = "x" * 500
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

    @patch("src.agent.graph.ChatGoogleGenerativeAI")
    @patch("src.agent.graph.logger")
    def test_emits_classifier_telemetry(
        self, mock_logger: MagicMock, mock_llm_class: MagicMock
    ) -> None:
        """Every classifier invocation logs decision + latency for observability."""
        mock_response = MagicMock()
        mock_response.content = "CHAT"
        mock_instance = MagicMock()
        mock_instance.invoke.return_value = mock_response
        mock_llm_class.return_value = mock_instance

        state: AgentState = {
            "messages": [HumanMessage(content="x" * 500)],
            "tool_retries": 0,
            "plan": "",
        }
        assert should_plan(state) == "chat"

        telemetry = [
            call
            for call in mock_logger.info.call_args_list
            if call.args and "planning_classifier" in call.args[0]
        ]
        assert telemetry, "expected a planning_classifier telemetry log"
        extra = telemetry[0].kwargs["extra"]
        assert extra["result"] == "chat"
        assert extra["content_length"] == 500
        assert "latency_ms" in extra

    @patch("src.agent.graph.Config")
    def test_message_below_threshold_skips_classifier(self, mock_config: MagicMock) -> None:
        """A message under MIN_LENGTH skips the classifier entirely (no LLM call)."""
        mock_config.AGENT_PLANNING_ENABLED = True
        mock_config.AGENT_PLANNING_MIN_LENGTH = 400
        state: AgentState = {
            "messages": [HumanMessage(content="x" * 300)],
            "tool_retries": 0,
            "plan": "",
        }
        assert should_plan(state) == "chat"


# ============ Compilation Tests ============


class TestGraphCompilation:
    """Tests for stateless graph compilation (no checkpointer)."""

    def test_compiles_without_checkpointer(self) -> None:
        """The chat graph is stateless: compile() takes no checkpointer."""
        mock_graph = MagicMock()
        compile_graph(mock_graph)
        mock_graph.compile.assert_called_once_with()

    def test_config_has_recursion_limit_only(self) -> None:
        """Graph config carries the recursion limit and no thread/checkpoint state."""
        config = get_graph_config()
        assert "recursion_limit" in config
        assert "configurable" not in config


# ============ Graph Structure Tests ============


class TestGraphStructure:
    """Tests for graph construction."""

    @patch("src.agent.graph.create_chat_model")
    @patch("src.agent.graph.create_tool_node")
    @patch("src.agent.graph.get_available_tools", lambda: [MagicMock(name="mock_tool")])
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

    @patch("src.agent.graph.with_retry")
    def test_cached_mode_uses_human_message_for_plan(self, mock_retry: MagicMock) -> None:
        """When use_cache=True, plan should be injected as HumanMessage."""
        from src.agent.graph import chat_node

        mock_model = MagicMock()
        mock_response = AIMessage(content="Cached response")
        # Capture the messages passed to invoke
        invoked_messages: list[list] = []

        def capture_invoke(msgs: list) -> AIMessage:
            invoked_messages.append(msgs)
            return mock_response

        mock_retry.return_value = capture_invoke

        state: AgentState = {
            "messages": [
                HumanMessage(content="[CONTEXT]\ndate info\n[/CONTEXT]"),
                HumanMessage(content="Do complex task"),
            ],
            "tool_retries": 0,
            "plan": "1. Search web\n2. Analyze results",
        }

        result = chat_node(state, mock_model, use_cache=True)

        # Plan should be cleared
        assert result.get("plan") == ""
        # The injected plan message should be a HumanMessage with SYSTEM GUIDANCE
        # markers, appended at the TAIL: inserting mid-history would change the
        # request prefix and bust Gemini's implicit caching of the history.
        assert len(invoked_messages) == 1
        msgs = invoked_messages[0]
        plan_msg = msgs[-1]
        assert isinstance(plan_msg, HumanMessage)
        assert "[SYSTEM GUIDANCE]" in plan_msg.content
        assert "[EXECUTION PLAN]" in plan_msg.content
        # The original history order is untouched
        assert msgs[0].content == "[CONTEXT]\ndate info\n[/CONTEXT]"
        assert msgs[1].content == "Do complex task"


# ============ plan_node Tool Awareness Tests ============


class TestPlanNodeToolAwareness:
    """plan_node must know the tool inventory.

    In cached mode the system prompt (which lists tools) lives in the Gemini
    cache, not in state, so without an explicit tool list the planner is asked
    to plan tool usage while blind to which tools exist.
    """

    @patch("src.agent.graph.with_retry")
    @patch("src.agent.graph.create_chat_model")
    def test_planning_prompt_includes_tool_names(
        self, mock_create_model: MagicMock, mock_retry: MagicMock
    ) -> None:
        from src.agent.graph import plan_node

        mock_create_model.return_value = MagicMock()
        captured: list[list] = []

        def capture_invoke(msgs: list) -> AIMessage:
            captured.append(msgs)
            return AIMessage(content="1. Search\n2. Summarize")

        mock_retry.return_value = capture_invoke

        state: AgentState = {
            "messages": [HumanMessage(content="Research X and summarize")],
            "tool_retries": 0,
            "plan": "",
        }
        result = plan_node(state, "test-model", tool_names=["web_search", "fetch_url"])

        assert result["plan"] == "1. Search\n2. Summarize"
        system_msg = captured[0][0]
        assert isinstance(system_msg, SystemMessage)
        assert "web_search" in system_msg.content
        assert "fetch_url" in system_msg.content


# ============ Cached Model Creation Tests ============


class TestCachedModelCreation:
    """Tests for create_chat_model with cached_content."""

    @patch("src.agent.graph.ChatGoogleGenerativeAI")
    def test_cached_content_passed_to_model(self, mock_llm_class: MagicMock) -> None:
        """cached_content should be passed as kwarg to ChatGoogleGenerativeAI."""
        from src.agent.graph import create_chat_model

        mock_instance = MagicMock()
        mock_llm_class.return_value = mock_instance

        create_chat_model(
            "test-model",
            with_tools=True,
            cached_content="cachedContents/abc123",
        )

        # Should be called with cached_content kwarg
        call_kwargs = mock_llm_class.call_args[1]
        assert call_kwargs["cached_content"] == "cachedContents/abc123"

    @patch("src.agent.graph.ChatGoogleGenerativeAI")
    def test_cached_mode_does_not_bind_tools(self, mock_llm_class: MagicMock) -> None:
        """When cached_content is provided, bind_tools should NOT be called."""
        from src.agent.graph import create_chat_model

        mock_instance = MagicMock()
        mock_llm_class.return_value = mock_instance

        result = create_chat_model(
            "test-model",
            with_tools=True,
            tools=[MagicMock(name="test_tool")],
            cached_content="cachedContents/abc123",
        )

        # bind_tools should not be called
        mock_instance.bind_tools.assert_not_called()
        # Should return the model directly
        assert result == mock_instance

    @patch("src.agent.graph.ChatGoogleGenerativeAI")
    def test_uncached_mode_binds_tools(self, mock_llm_class: MagicMock) -> None:
        """Without cached_content, tools should be bound normally."""
        from src.agent.graph import create_chat_model

        mock_instance = MagicMock()
        mock_llm_class.return_value = mock_instance
        mock_tool = MagicMock(name="test_tool")

        create_chat_model(
            "test-model",
            with_tools=True,
            tools=[mock_tool],
        )

        # bind_tools should be called
        mock_instance.bind_tools.assert_called_once_with([mock_tool])


# ============ Cached check_tool_results Tests ============


class TestCachedCheckToolResults:
    """Tests for check_tool_results with use_cache=True."""

    def test_cached_mode_uses_human_message_for_guidance(self) -> None:
        """In cached mode, error guidance should use HumanMessage."""
        state: AgentState = {
            "messages": [
                AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "1"}]),
                ToolMessage(content='{"error": "API returned 500"}', tool_call_id="1"),
            ],
            "tool_retries": 0,
            "plan": "",
        }
        result = check_tool_results(state, use_cache=True)
        assert result["tool_retries"] == 1
        guidance = result["messages"][0]
        assert isinstance(guidance, HumanMessage)
        assert "[SYSTEM GUIDANCE]" in guidance.content

    def test_uncached_mode_uses_system_message_for_guidance(self) -> None:
        """In uncached mode, error guidance should use SystemMessage."""
        state: AgentState = {
            "messages": [
                AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "1"}]),
                ToolMessage(content='{"error": "API returned 500"}', tool_call_id="1"),
            ],
            "tool_retries": 0,
            "plan": "",
        }
        result = check_tool_results(state, use_cache=False)
        assert result["tool_retries"] == 1
        guidance = result["messages"][0]
        assert isinstance(guidance, SystemMessage)
        assert "[SYSTEM GUIDANCE]" not in guidance.content


# ============ Tool Result Aging Tests ============


class TestAgeConsumedToolMessages:
    """Within-turn aging of already-consumed tool results (cost control).

    Fresh results (answers to the latest tool-calling AIMessage) must pass
    through untouched - the model has not seen them yet. Older results are
    re-sent on every loop iteration after the model consumed them, so
    multimodal content becomes a stub and long text is truncated.
    """

    def _messages_two_rounds(self) -> list:
        pdf_content = [
            {"type": "text", "text": "PDF from example.com:"},
            {"type": "image", "base64": "x" * 100_000, "mime_type": "application/pdf"},
        ]
        return [
            HumanMessage(content="summarize this pdf and search for reviews"),
            AIMessage(content="", tool_calls=[{"name": "fetch_url", "args": {}, "id": "c1"}]),
            ToolMessage(content=pdf_content, tool_call_id="c1", name="fetch_url"),
            AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "c2"}]),
            ToolMessage(content='{"results": []}', tool_call_id="c2", name="web_search"),
        ]

    def test_consumed_multimodal_result_becomes_stub(self) -> None:
        from src.agent.graph import AGED_MULTIMODAL_STUB, _age_consumed_tool_messages

        messages = self._messages_two_rounds()
        _age_consumed_tool_messages(messages)

        assert messages[2].content == AGED_MULTIMODAL_STUB

    def test_fresh_results_untouched(self) -> None:
        from src.agent.graph import _age_consumed_tool_messages

        messages = self._messages_two_rounds()
        _age_consumed_tool_messages(messages)

        # The web_search result answers the LATEST tool-calling AIMessage
        assert messages[4].content == '{"results": []}'

    def test_fresh_multimodal_untouched(self) -> None:
        """A binary result the model has NOT yet seen must pass through."""
        from src.agent.graph import _age_consumed_tool_messages

        pdf_content = [{"type": "image", "base64": "x" * 1000, "mime_type": "application/pdf"}]
        messages = [
            HumanMessage(content="read this"),
            AIMessage(content="", tool_calls=[{"name": "fetch_url", "args": {}, "id": "c1"}]),
            ToolMessage(content=pdf_content, tool_call_id="c1", name="fetch_url"),
        ]
        _age_consumed_tool_messages(messages)

        assert messages[2].content == pdf_content

    def test_consumed_long_text_truncated(self) -> None:
        from src.agent.graph import AGED_TRUNCATION_MARKER, _age_consumed_tool_messages

        long_text = "a" * 10_000
        messages = [
            AIMessage(content="", tool_calls=[{"name": "fetch_url", "args": {}, "id": "c1"}]),
            ToolMessage(content=long_text, tool_call_id="c1", name="fetch_url"),
            AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "c2"}]),
            ToolMessage(content="fresh", tool_call_id="c2", name="web_search"),
        ]
        _age_consumed_tool_messages(messages)

        assert messages[1].content.endswith(AGED_TRUNCATION_MARKER)
        assert len(messages[1].content) < 10_000
        assert messages[3].content == "fresh"

    def test_short_consumed_text_untouched(self) -> None:
        from src.agent.graph import _age_consumed_tool_messages

        messages = [
            AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "c1"}]),
            ToolMessage(content="short result", tool_call_id="c1", name="web_search"),
            AIMessage(content="", tool_calls=[{"name": "fetch_url", "args": {}, "id": "c2"}]),
            ToolMessage(content="fresh", tool_call_id="c2", name="fetch_url"),
        ]
        _age_consumed_tool_messages(messages)

        assert messages[1].content == "short result"

    @patch("src.agent.graph.Config")
    def test_disabled_when_zero(self, mock_config: MagicMock) -> None:
        from src.agent.graph import _age_consumed_tool_messages

        mock_config.AGENT_AGED_TOOL_RESULT_MAX_CHARS = 0
        messages = self._messages_two_rounds()
        original = messages[2].content
        _age_consumed_tool_messages(messages)

        assert messages[2].content == original


# ============ Tool Node Exception Handling Tests ============


class TestToolNodeApprovalPropagation:
    """ApprovalRequestedException must escape the ToolNode's error handling.

    Regression test: with handle_tool_errors=True (langgraph >= 1.0), ALL
    Exception subclasses raised by tools are converted into error ToolMessages,
    which silently broke the autonomous-agent approval flow — the executor's
    `except ApprovalRequestedException` never fired and executions completed
    instead of pausing in waiting_approval.
    """

    def test_approval_exception_propagates_through_compiled_graph(self) -> None:
        """request_approval's control-flow exception must reach the caller."""
        from src.agent.tools.request_approval import ApprovalRequestedException

        @tool
        def sensitive_action(description: str) -> str:
            """Perform a sensitive action."""
            raise ApprovalRequestedException("approval-1", description, "todoist")

        compiled = _compile_tool_graph([sensitive_action])
        state = _tool_call_state(
            [{"name": "sensitive_action", "args": {"description": "send email"}, "id": "c1"}]
        )

        with pytest.raises(ApprovalRequestedException) as exc_info:
            compiled.invoke(state)
        assert exc_info.value.approval_id == "approval-1"

    def test_ordinary_tool_error_still_becomes_error_tool_message(self) -> None:
        """Non-control-flow tool exceptions keep the self-healing behavior."""

        @tool
        def boom(query: str) -> str:
            """Always fails."""
            raise ValueError("boom")

        compiled = _compile_tool_graph([boom])
        state = _tool_call_state([{"name": "boom", "args": {"query": "x"}, "id": "c1"}])

        result = compiled.invoke(state)
        last = result["messages"][-1]
        assert isinstance(last, ToolMessage)
        assert last.status == "error"
        assert "boom" in last.content


# ============ Autonomous Permission Filtering Tests ============


@tool
def echo(text: str) -> str:
    """Echo the input back."""
    return f"echo: {text}"


@tool
def forbidden_tool(text: str) -> str:
    """A tool the agent is not permitted to use."""
    return "should never run"


class TestToolNodePermissionFiltering:
    """Blocked tool calls must not drop sibling calls in the same batch.

    Every tool_call_id needs a ToolMessage response (Gemini rejects the next
    turn on a call/response mismatch), and allowed calls in the same batch
    must still execute.
    """

    @pytest.fixture(autouse=True)
    def _agent_context(self) -> Any:
        """Install an autonomous-agent context permitting only `echo`."""
        from src.agent.executor import AgentContext, clear_agent_context, set_agent_context

        agent = MagicMock()
        agent.id = "agent-1"
        agent.tool_permissions = ["echo"]
        set_agent_context(AgentContext(agent=agent, user=MagicMock(), trigger_chain=[]))
        yield
        clear_agent_context()

    def test_blocked_call_does_not_drop_allowed_sibling(self) -> None:
        """One blocked + one allowed call → two ToolMessages, allowed executed."""
        compiled = _compile_tool_graph([echo, forbidden_tool], is_autonomous=True)
        state = _tool_call_state(
            [
                {"name": "forbidden_tool", "args": {"text": "x"}, "id": "c1"},
                {"name": "echo", "args": {"text": "hello"}, "id": "c2"},
            ]
        )

        result = compiled.invoke(state)
        tool_messages = {
            m.tool_call_id: m for m in result["messages"] if isinstance(m, ToolMessage)
        }

        assert set(tool_messages) == {"c1", "c2"}
        assert "not permitted" in tool_messages["c1"].content
        assert tool_messages["c1"].status == "error"
        assert tool_messages["c2"].content == "echo: hello"

    def test_all_calls_blocked_returns_response_per_call(self) -> None:
        """Two blocked calls → two error ToolMessages, nothing executed."""
        compiled = _compile_tool_graph([echo, forbidden_tool], is_autonomous=True)
        state = _tool_call_state(
            [
                {"name": "forbidden_tool", "args": {"text": "x"}, "id": "c1"},
                {"name": "forbidden_tool", "args": {"text": "y"}, "id": "c2"},
            ]
        )

        result = compiled.invoke(state)
        tool_messages = {
            m.tool_call_id: m for m in result["messages"] if isinstance(m, ToolMessage)
        }

        assert set(tool_messages) == {"c1", "c2"}
        assert all("not permitted" in m.content for m in tool_messages.values())

    def test_all_allowed_executes_normally(self) -> None:
        """No blocked calls → normal execution path."""
        compiled = _compile_tool_graph([echo], is_autonomous=True)
        state = _tool_call_state([{"name": "echo", "args": {"text": "hi"}, "id": "c1"}])

        result = compiled.invoke(state)
        last = result["messages"][-1]
        assert isinstance(last, ToolMessage)
        assert last.content == "echo: hi"
