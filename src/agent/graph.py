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

import threading
import time
from collections import OrderedDict
from typing import Any, Literal

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode as BaseToolNode

from src.agent.cancellation import TurnCancelled
from src.agent.chat_model import create_chat_model, fallback_model_factory
from src.agent.chat_node import chat_node
from src.agent.content import (
    extract_text_content,
    strip_echoed_msg_context,
    strip_full_result_from_tool_content,
)
from src.agent.graph_state import AgentState
from src.agent.permissions import PermissionResult, check_tool_permission
from src.agent.tool_results import get_current_request_id, store_tool_result
from src.agent.tool_round_check import check_tool_results
from src.agent.tools import get_available_tools
from src.agent.tools.metadata import EXTRACT_ONLY_TOOL_NAMES
from src.agent.tools.request_approval import ApprovalRequestedException
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


# Import permission-related modules (at module level to avoid repeated imports)
# These are only used when is_autonomous=True
def _get_permission_modules() -> dict[str, Any]:
    """The permission helpers; get_agent_context is imported lazily (cycle)."""
    from src.agent.executor import get_agent_context  # noqa: PLC0415 - cycle: executor -> agent -> stream_events -> graph

    return {
        "get_agent_context": get_agent_context,
        "check_tool_permission": check_tool_permission,
        "PermissionResult": PermissionResult,
    }


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


def _handle_tool_errors(e: Exception) -> str:
    """Convert tool exceptions into error ToolMessages, except control-flow exceptions.

    ApprovalRequestedException is control flow, not an error: it must propagate
    to the executor/streaming handler so the run pauses in waiting_approval.
    TurnCancelled (the user pressed Stop) likewise must end the turn, not become
    an error ToolMessage the model then reacts to.
    handle_tool_errors=True would swallow it into an error ToolMessage
    (verified on langgraph 1.0.5), silently completing the run instead.

    The returned string mirrors langgraph's default TOOL_CALL_ERROR_TEMPLATE so
    ordinary tool errors keep the exact same self-correction behavior.
    """
    if isinstance(e, (ApprovalRequestedException, TurnCancelled)):
        raise e
    return f"Error: {e!r}\n Please fix your mistakes."


def _split_blocked_tool_calls(
    state: AgentState,
    modules: dict[str, Any],
    agent: Any,
) -> tuple[list[ToolMessage], AgentState | None]:
    """Split pending tool calls into blocked error responses and an executable state.

    Returns (blocked_tool_messages, state_with_only_allowed_calls). The state
    is None when every call was blocked (nothing left to execute), and the
    original state when nothing was blocked.
    """
    last_message = state["messages"][-1]
    if not (isinstance(last_message, AIMessage) and last_message.tool_calls):
        return [], state

    blocked: list[ToolMessage] = []
    allowed: list[Any] = []
    for tool_call in last_message.tool_calls:
        tool_name = tool_call.get("name")
        permission = (
            modules["check_tool_permission"](agent, tool_name, tool_call.get("args", {}))
            if tool_name
            else modules["PermissionResult"].ALLOWED
        )
        if permission == modules["PermissionResult"].BLOCKED:
            blocked.append(
                ToolMessage(
                    content=f"Tool '{tool_name}' is not permitted for this agent",
                    tool_call_id=tool_call.get("id", ""),
                    status="error",
                )
            )
        else:
            allowed.append(tool_call)

    if not blocked:
        return [], state
    if not allowed:
        return blocked, None

    # Re-issue the AIMessage with only the allowed calls for the base ToolNode
    pruned = AIMessage(content=last_message.content, tool_calls=allowed)
    exec_state: AgentState = {**state, "messages": [*state["messages"][:-1], pruned]}
    return blocked, exec_state


def _split_approval_tool_calls(
    state: AgentState,
) -> tuple[AgentState | None, AgentState | None]:
    """Split request_approval calls from their batch siblings (R3).

    request_approval pauses the whole run by raising; executed alongside
    siblings, their ToolMessages were discarded with the aborted node - work
    already done server-side went unrecorded and was redone after approval.

    Returns (approval_only_state, siblings_state); either is None when empty.
    When there are no approval calls, returns (None, state) unchanged.
    """
    last_message = state["messages"][-1]
    if not (isinstance(last_message, AIMessage) and last_message.tool_calls):
        return None, state

    approval_calls = [tc for tc in last_message.tool_calls if tc.get("name") == "request_approval"]
    if not approval_calls:
        return None, state
    sibling_calls = [tc for tc in last_message.tool_calls if tc.get("name") != "request_approval"]

    def _with_calls(calls: list[Any]) -> AgentState:
        pruned = AIMessage(content=last_message.content, tool_calls=calls)
        return {**state, "messages": [*state["messages"][:-1], pruned]}

    approval_state = _with_calls(approval_calls)
    siblings_state = _with_calls(sibling_calls) if sibling_calls else None
    return approval_state, siblings_state


def _log_tool_round(messages: list[Any], elapsed_ms: int) -> None:
    """Record what a tool round ran, how it ended, and how long it took.

    Until Sep 2026 nothing logged tool timing at all: the only way to see how
    slow a tool was, was to diff the timestamps of the LLM calls around it.
    Since ~95% of rounds carry a single tool call, the round's wall-clock is
    that tool's latency; batched rounds run concurrently, so the round time is
    the number that actually matters there too.
    """
    outcomes = [
        {
            "tool": msg.name or "unknown",
            "status": getattr(msg, "status", None) or "success",
            "result_chars": len(msg.content) if isinstance(msg.content, str) else None,
        }
        for msg in messages
        if isinstance(msg, ToolMessage)
    ]
    if not outcomes:
        return

    logger.info(
        "Tool round completed",
        extra={
            "tools": [o["tool"] for o in outcomes],
            "count": len(outcomes),
            "elapsed_ms": elapsed_ms,
            "outcomes": outcomes,
        },
    )


def _capture_and_strip_tool_messages(messages: list[Any], request_id: str | None) -> None:
    """Store original tool results for server-side extraction, then strip
    _full_result payloads (e.g. generated images) before they reach the LLM."""
    for msg in messages:
        if isinstance(msg, ToolMessage) and isinstance(msg.content, str):
            if request_id is not None:
                store_tool_result(request_id, msg.content)

            content_len_before = len(msg.content)
            msg.content = strip_full_result_from_tool_content(msg.content)
            content_len_after = len(msg.content)
            if content_len_before != content_len_after:
                logger.info(
                    "Stripped _full_result from tool message",
                    extra={
                        "content_len_before": content_len_before,
                        "content_len_after": content_len_after,
                        "bytes_saved": content_len_before - content_len_after,
                    },
                )


_SIBLING_RESULT_MAX_CHARS = 500


def _summarize_sibling_results(messages: list[Any]) -> list[tuple[str, str]]:
    """Compact (tool_name, result) pairs for the approval pause message."""
    summaries: list[tuple[str, str]] = []
    for msg in messages:
        if isinstance(msg, ToolMessage) and isinstance(msg.content, str):
            content = msg.content
            if len(content) > _SIBLING_RESULT_MAX_CHARS:
                content = content[:_SIBLING_RESULT_MAX_CHARS] + "…"
            summaries.append((msg.name or "tool", content))
    return summaries


def create_tool_node(tools: list[Any], is_autonomous: bool = False) -> Any:
    """Create a tool node that strips large data from results before sending to LLM.

    This prevents the ~650K token cost of sending generated images back to the model.
    The full tool results are still captured separately for server-side extraction.

    The request ID is read from the _current_request_id contextvar at runtime,
    allowing per-request capture while using a single shared graph instance.

    For autonomous agents (is_autonomous=True), this also checks tool permissions
    and may raise ApprovalRequestedException if a tool call requires user approval.

    Args:
        tools: List of tools to use
        is_autonomous: If True, check permissions and require approval for dangerous operations
    """
    base_tool_node = BaseToolNode(tools, handle_tool_errors=_handle_tool_errors)

    def tool_node_with_stripping(state: AgentState) -> dict[str, Any]:
        """Execute tools and strip _full_result from results."""
        logger.debug("tool_node_with_stripping starting", extra={"is_autonomous": is_autonomous})

        # Get the current request ID from contextvar
        request_id = get_current_request_id()

        # For autonomous agents, split blocked calls out of the batch. Every
        # tool_call_id must get a ToolMessage (Gemini rejects the next turn on
        # a call/response mismatch) and allowed siblings must still execute.
        blocked_messages: list[ToolMessage] = []
        exec_state: AgentState | None = state
        if is_autonomous:
            modules = _get_permission_modules()
            agent_context = modules["get_agent_context"]()
            if agent_context:
                blocked_messages, exec_state = _split_blocked_tool_calls(
                    state, modules, agent_context.agent
                )

        # R3: run request_approval AFTER its batch siblings. It pauses the
        # whole run by raising; executed alongside siblings, their results
        # were discarded with the aborted node.
        approval_state: AgentState | None = None
        if is_autonomous and exec_state is not None:
            approval_state, exec_state = _split_approval_tool_calls(exec_state)

        if exec_state is None:
            # Every call was blocked (or was an approval request)
            result: dict[str, Any] = {"messages": blocked_messages}
        else:
            started = time.monotonic()
            result = base_tool_node.invoke(exec_state)
            _log_tool_round(result.get("messages", []), int((time.monotonic() - started) * 1000))
            if blocked_messages:
                result["messages"] = blocked_messages + list(result.get("messages", []))

        _capture_and_strip_tool_messages(result.get("messages", []), request_id)

        if approval_state is not None:
            try:
                approval_result = base_tool_node.invoke(approval_state)
            except ApprovalRequestedException as e:
                # Record what already ran so the post-approval run doesn't
                # redo or forget it (the pause discards this node's output)
                e.sibling_results = _summarize_sibling_results(result.get("messages", []))
                raise
            # request_approval returned without pausing (e.g. outside agent
            # context) - merge its error message normally
            _capture_and_strip_tool_messages(approval_result.get("messages", []), request_id)
            result["messages"] = list(result.get("messages", [])) + list(
                approval_result.get("messages", [])
            )

        logger.debug("tool_node_with_stripping completed")
        return result

    return tool_node_with_stripping


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

# per-worker: a memo of compiled graphs, rebuilt on a miss
_compiled_graph_cache: OrderedDict[tuple[Any, ...], Any] = OrderedDict()
_compiled_graph_lock = threading.Lock()

# Context-cache names kept per otherwise-identical signature. The name rotates
# whenever a Gemini cache lapses or is recreated, so without this cap every dead
# name stays compiled until the global LRU evicts it (~2.5 MB per graph). Three
# covers the live set: the uncached fallback (None) plus SPORTS and LANGUAGE,
# the two profiles that bind the same tools.
_MAX_CACHE_NAMES_PER_SIGNATURE = 3


def _graph_signature(
    model_name: str,
    with_tools: bool,
    include_thoughts: bool,
    tools: list[Any],
    is_autonomous: bool,
    thinking_level: str | None,
    cached_content: str | None,
) -> tuple[Any, ...]:
    """Everything the compiled graph depends on. Tool names are sorted so the
    key is order-independent (the tool set, not its ordering, matters).
    cached_content stays last: the per-signature name cap slices it off."""
    tool_sig = tuple(sorted(t.name for t in tools)) if tools else ()
    return (
        model_name,
        with_tools,
        include_thoughts,
        tool_sig,
        is_autonomous,
        thinking_level,
        cached_content,
    )


def clear_graph_cache() -> None:
    """Drop all memoized compiled graphs (used by tests for isolation)."""
    with _compiled_graph_lock:
        _compiled_graph_cache.clear()


def get_compiled_graph(
    model_name: str,
    with_tools: bool = True,
    include_thoughts: bool = False,
    tools: list[Any] | None = None,
    is_autonomous: bool = False,
    cached_content: str | None = None,
    memoize: bool = True,
    thinking_level: str | None = None,
) -> Any:
    """Return a compiled chat graph for this signature, building it once.

    `memoize=False` for tools that are per-run closures (deep research wraps
    its tools around each run's board, with the same names every run): the
    signature knows only tool names, so a memoized graph would run an earlier
    run's tools.

    Bounded LRU (Config.AGENT_GRAPH_CACHE_SIZE): the cached_content name rotates
    hourly, so stale entries are evicted rather than accumulating unbounded.
    """
    active_tools = tools if tools is not None else get_available_tools()
    if not memoize:
        return compile_graph(
            create_chat_graph(
                model_name,
                with_tools=with_tools,
                include_thoughts=include_thoughts,
                tools=active_tools,
                is_autonomous=is_autonomous,
                cached_content=cached_content,
                thinking_level=thinking_level,
            )
        )
    key = _graph_signature(
        model_name,
        with_tools,
        include_thoughts,
        active_tools,
        is_autonomous,
        thinking_level,
        cached_content,
    )

    with _compiled_graph_lock:
        cached = _compiled_graph_cache.get(key)
        if cached is not None:
            _compiled_graph_cache.move_to_end(key)  # mark most-recently-used
            return cached

    # Build outside the lock - compilation is the slow part we don't want to
    # serialize. A rare concurrent double-build is harmless (both are valid);
    # the second store just overwrites with an equivalent graph.
    compiled = compile_graph(
        create_chat_graph(
            model_name,
            with_tools=with_tools,
            include_thoughts=include_thoughts,
            tools=active_tools,
            is_autonomous=is_autonomous,
            cached_content=cached_content,
            thinking_level=thinking_level,
        )
    )

    with _compiled_graph_lock:
        _compiled_graph_cache[key] = compiled
        _compiled_graph_cache.move_to_end(key)
        # cached_content is the last signature element; drop this signature's
        # least-recently-used names beyond the cap (dead rotated caches)
        same_signature = [k for k in _compiled_graph_cache if k[:-1] == key[:-1]]
        for stale in same_signature[:-_MAX_CACHE_NAMES_PER_SIGNATURE]:
            del _compiled_graph_cache[stale]
        max_size = Config.AGENT_GRAPH_CACHE_SIZE
        while max_size > 0 and len(_compiled_graph_cache) > max_size:
            _compiled_graph_cache.popitem(last=False)  # evict least-recently-used
    return compiled


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
