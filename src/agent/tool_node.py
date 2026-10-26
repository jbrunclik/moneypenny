"""The graph's tool node: runs a round's tool calls, permission checks and approvals.

Wraps LangGraph's ToolNode so that large payloads are captured and stripped
before the results reach the model, autonomous agents' blocked calls get an
error result, and request_approval runs after its batch siblings.
"""

import time
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt import ToolNode as BaseToolNode

from src.agent.cancellation import TurnCancelled
from src.agent.content import strip_full_result_from_tool_content
from src.agent.graph_state import AgentState
from src.agent.permissions import PermissionResult, check_tool_permission
from src.agent.tool_results import get_current_request_id, store_tool_result
from src.agent.tools.request_approval import ApprovalRequestedException
from src.utils.logging import get_logger

logger = get_logger(__name__)


# Import permission-related modules (at module level to avoid repeated imports)
# These are only used when is_autonomous=True
def _get_permission_modules() -> dict[str, Any]:
    """The permission helpers; get_agent_context is imported lazily (cycle)."""
    from src.agent.executor import get_agent_context  # noqa: PLC0415 - cycle: executor -> agent -> graph -> tool_node

    return {
        "get_agent_context": get_agent_context,
        "check_tool_permission": check_tool_permission,
        "PermissionResult": PermissionResult,
    }


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


def _split_autonomous_calls(
    state: AgentState,
) -> tuple[list[ToolMessage], AgentState | None, AgentState | None]:
    """(blocked messages, state to execute, approval-only state) for an autonomous agent.

    Blocked calls are split out of the batch: every tool_call_id must get a
    ToolMessage (Gemini rejects the next turn on a call/response mismatch)
    and allowed siblings must still execute.

    R3: request_approval runs AFTER its batch siblings. It pauses the whole
    run by raising; executed alongside siblings, their results were
    discarded with the aborted node.
    """
    blocked_messages: list[ToolMessage] = []
    exec_state: AgentState | None = state
    modules = _get_permission_modules()
    agent_context = modules["get_agent_context"]()
    if agent_context:
        blocked_messages, exec_state = _split_blocked_tool_calls(
            state, modules, agent_context.agent
        )

    approval_state: AgentState | None = None
    if exec_state is not None:
        approval_state, exec_state = _split_approval_tool_calls(exec_state)
    return blocked_messages, exec_state, approval_state


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


def _run_batch(
    base_tool_node: BaseToolNode,
    exec_state: AgentState | None,
    blocked_messages: list[ToolMessage],
) -> dict[str, Any]:
    """Execute the round's allowed calls, blocked calls' errors first."""
    if exec_state is None:
        # Every call was blocked (or was an approval request)
        return {"messages": blocked_messages}
    started = time.monotonic()
    result: dict[str, Any] = base_tool_node.invoke(exec_state)
    _log_tool_round(result.get("messages", []), int((time.monotonic() - started) * 1000))
    if blocked_messages:
        result["messages"] = blocked_messages + list(result.get("messages", []))
    return result


def _run_approval(
    base_tool_node: BaseToolNode,
    approval_state: AgentState,
    result: dict[str, Any],
    request_id: str | None,
) -> None:
    """Run request_approval after its siblings, appending its result to `result`."""
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

        blocked_messages: list[ToolMessage] = []
        exec_state: AgentState | None = state
        approval_state: AgentState | None = None
        if is_autonomous:
            blocked_messages, exec_state, approval_state = _split_autonomous_calls(state)

        result = _run_batch(base_tool_node, exec_state, blocked_messages)
        _capture_and_strip_tool_messages(result.get("messages", []), request_id)

        if approval_state is not None:
            _run_approval(base_tool_node, approval_state, result, request_id)

        logger.debug("tool_node_with_stripping completed")
        return result

    return tool_node_with_stripping
