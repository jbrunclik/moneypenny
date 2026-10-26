"""LangGraph chat graph construction for the chat agent.

This module handles creating and configuring the LangGraph state machine
that powers the chat agent's conversation flow with tool support.

Graph flow (with tools):
  START -> chat -> should_continue -> "tools": tools -> check_tool_results -> chat (loop)
                                   -> "end": END

Graph flow (without tools):
  START -> chat -> END

Multi-step planning is the model's own job (Gemini native thinking - see the
thinking_level knob in Config.MODELS); the old classifier+plan-node subsystem
was removed in Aug 2026 (git history has it).
"""

from typing import Any, Literal

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph

from src.agent.chat_model import create_chat_model, fallback_model_factory
from src.agent.chat_node import chat_node
from src.agent.content import (
    extract_text_content,
    strip_echoed_msg_context,
)
from src.agent.graph_state import AgentState
from src.agent.tool_node import create_tool_node
from src.agent.tool_round_check import check_tool_results
from src.agent.tools import get_available_tools
from src.agent.tools.metadata import EXTRACT_ONLY_TOOL_NAMES
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


# ============ Model Creation ============


# ============ Graph Nodes ============


def should_continue(state: AgentState) -> Literal["tools", "end"]:
    """Decide whether to continue to tools or end the conversation.

    When all tool calls in the final message are extract-only (set_conversation_title)
    AND the LLM already produced text, routes to "end" instead of "tools" to
    avoid an extra LLM round-trip. Those tool call args are read from the
    AIMessage in post-processing, so executing them would be a no-op.

    If the LLM produced extract-only tool calls but NO text, routes to "tools"
    so the tools execute normally and the LLM gets another turn to respond with
    text. This prevents empty messages.

    Note that manage_memory is deliberately NOT extract-only: it performs real
    writes and the model needs to read their outcome, so it always executes.
    """
    messages = state["messages"]
    last_message = messages[-1]

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        if all(tc["name"] in EXTRACT_ONLY_TOOL_NAMES for tc in last_message.tool_calls):
            # If LLM already generated text alongside metadata tools,
            # skip execution - args are extracted in post-processing. An
            # echoed MSG_CONTEXT is stripped before saving, so it is no answer.
            text = strip_echoed_msg_context(extract_text_content(last_message.content))
            if text.strip():
                return "end"
            # No text generated - execute tools so LLM gets another
            # turn to produce a text response
            return "tools"
        return "tools"

    return "end"


# ============ Tool Node Factory ============


# ============ Graph Factory ============


def create_chat_graph(
    model_name: str,
    with_tools: bool = True,
    include_thoughts: bool = False,
    tools: list[Any] | None = None,
    is_autonomous: bool = False,
    cached_content: str | None = None,
    thinking_level: str | None = None,
) -> StateGraph[AgentState]:
    """Create a chat graph with optional tool support.

    The graph includes:
    - Chat node (LLM invocation)
    - Tool node (with error handling and result stripping)
    - Self-correction node (inspects tool errors and guides retries)

    Args:
        model_name: The Gemini model to use
        with_tools: Whether to bind tools to the model
        include_thoughts: Whether to include thinking/reasoning summaries
        tools: Custom list of tools to use (defaults to get_available_tools())
        is_autonomous: If True, check permissions and require approval for dangerous operations
        cached_content: Gemini cached content name (tools are in the cache, not bound)
        thinking_level: Overrides the model's configured thinking_level
    """
    active_tools = tools if tools is not None else get_available_tools()
    model = create_chat_model(
        model_name,
        with_tools=with_tools,
        include_thoughts=include_thoughts,
        tools=active_tools,
        cached_content=cached_content,
        thinking_level=thinking_level,
    )

    # Capture whether cache is active for nodes that inject guidance messages
    use_cache = cached_content is not None

    # Define the graph
    graph: StateGraph[AgentState] = StateGraph(AgentState)

    fallback = fallback_model_factory(model_name, with_tools, include_thoughts, active_tools)

    # Add the chat node
    graph.add_node(
        "chat",
        lambda state, config: chat_node(
            state, model, use_cache=use_cache, config=config, fallback=fallback
        ),
    )

    if with_tools and active_tools:
        # Add tool node with stripping of large results and error handling
        tool_node = create_tool_node(active_tools, is_autonomous=is_autonomous)
        graph.add_node("tools", tool_node)

        # Add self-correction node
        graph.add_node(
            "check_tool_results",
            lambda state: check_tool_results(state, use_cache=use_cache),
        )

        graph.set_entry_point("chat")

        # Add conditional edge based on whether to use tools
        graph.add_conditional_edges("chat", should_continue, {"tools": "tools", "end": END})

        # After tools, check results for errors
        graph.add_edge("tools", "check_tool_results")

        # After checking results, go back to chat
        graph.add_edge("check_tool_results", "chat")
    else:
        # Simple graph without tools
        graph.set_entry_point("chat")
        graph.add_edge("chat", END)

    return graph


# ============ Compiled-graph memoization ============
#
# create_chat_graph + compile_graph ran in ChatAgent.__init__ on every request,
# rebuilding + recompiling a graph that is a pure function of its build
# signature. The compiled graph is stateless (state is passed per invoke; the
# request id rides a contextvar, not the graph), so it is safe to compile once
# per signature and share across requests and threads.


def compile_graph(graph: StateGraph[AgentState]) -> Any:
    """Compile a StateGraph for execution.

    The graph is stateless across requests: every invoke receives the full
    message list to send, so no checkpointer is attached. Within-request
    multi-step state (the tool loop) is held in memory during the invoke.

    Args:
        graph: The StateGraph to compile

    Returns:
        Compiled graph ready for invoke/stream
    """
    return graph.compile()


def get_graph_config() -> dict[str, Any]:
    """Build the config dict for graph invoke/stream calls."""
    return {"recursion_limit": Config.AGENT_RECURSION_LIMIT}
