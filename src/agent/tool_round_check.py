"""The graph's check_tool_results node: steering, turn budgets and self-correction.

Runs after every tool round and always routes back to chat; what it adds to
the state tells the model how to go on.
"""

import json
from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from src.agent import interjection
from src.agent.cancellation import raise_if_cancelled
from src.agent.graph_state import AgentState
from src.agent.tool_loops import loop_state
from src.agent.tools.context import get_conversation_context
from src.agent.turn_budget import (
    BATCHING_HINT,
    FINAL_GUIDANCE,
    WRAP_UP_NOTICE,
    batching_hint_due,
    budget_stop,
    log_stop,
    wrap_up_due,
)
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# A node's state update (LangGraph merges it into the state)
Update = dict[str, Any]


def tool_message_error(msg: ToolMessage) -> tuple[str, bool] | None:
    """Return (error_text, retriable) if the ToolMessage is a failure, else None.

    Detection is structural — never substring matching, which false-positived
    on legitimate content (e.g. a fetched page that *describes* a failure):
    - status == "error": set by the ToolNode exception handler and the
      permission-blocked path
    - a JSON object with a truthy "error" key: the envelope every tool in
      src/agent/tools returns on failure

    Tools mark permanent failures (integration not configured, invalid
    action, ...) with "retriable": false so self-correction skips pointless
    retries; absent flag defaults to retriable.
    """
    if getattr(msg, "status", None) == "error":
        return str(msg.content)[:200], True
    if isinstance(msg.content, str):
        try:
            data = json.loads(msg.content)
        except json.JSONDecodeError, TypeError:
            return None
        if isinstance(data, dict) and data.get("error"):
            return str(data["error"])[:200], bool(data.get("retriable", True))
    return None


def _guidance(content: str, use_cache: bool) -> BaseMessage:
    """Guidance for the model's next call.

    In cached mode it is a wrapped HumanMessage: LangChain drops
    mid-conversation SystemMessages there.
    """
    if use_cache:
        return HumanMessage(content=f"[SYSTEM GUIDANCE]\n{content}\n[/SYSTEM GUIDANCE]")
    return SystemMessage(content=content)


def _interjection_update(state: AgentState, tool_rounds: int, use_cache: bool) -> Update | None:
    """Mid-run steering the user sent while this turn was running, if any.

    Stored cross-worker in kv_store by the interject route. Popped before the
    budgets decide, so steering is never swallowed - it rides along with a
    stop or the wrap-up notice.
    """
    conv_id, user_id = get_conversation_context()
    if not (conv_id and user_id):
        return None
    steer_text = interjection.pop_interjection(user_id, conv_id)
    if not steer_text:
        return None
    logger.info(
        "Interjection injected between tool rounds",
        extra={"conversation_id": conv_id, "tool_rounds": tool_rounds},
    )
    steer_content = (
        "[USER INTERJECTION] The user just sent this while you were "
        f'working: "{steer_text}"\n'
        "Adjust course immediately: incorporate this guidance into the "
        "current task, drop work it makes irrelevant, and acknowledge "
        "the change in your final answer."
    )
    return {
        "tool_rounds": tool_rounds,
        "tool_retries": state.get("tool_retries", 0),
        "messages": [_guidance(steer_content, use_cache)],
    }


def _budget_update(
    state: AgentState,
    tool_rounds: int,
    use_cache: bool,
    interjection: dict[str, object] | None,
) -> dict[str, object] | None:
    """Turn budgets: a stop (the final, tools-off answer comes next) or the one
    wrap-up notice; None when neither, so self-correction runs as usual.

    An interjection always reaches the model, also after a stop - it never
    re-opens the tools.
    """
    found = interjection["messages"] if interjection else []
    steering: list[BaseMessage] = list(found) if isinstance(found, list) else []
    if reason := state.get("final_answer"):
        return {"tool_rounds": tool_rounds, "final_answer": reason, "messages": steering}
    if stop := budget_stop(state, tool_rounds):
        log_stop(stop, state, tool_rounds)
        guidance = _guidance(FINAL_GUIDANCE, use_cache)
        return {
            "tool_rounds": tool_rounds,
            "tool_retries": 0,
            "final_answer": stop,
            "messages": [*steering, guidance],
        }
    latest = state["messages"][-1] if state["messages"] else None
    if wrap_up_due(state) and isinstance(latest, ToolMessage):
        logger.info("Turn wrap-up notice", extra={"tool_rounds": tool_rounds})
        notice = latest.model_copy(update={"content": f"{latest.content}{WRAP_UP_NOTICE}"})
        return {
            "tool_rounds": tool_rounds,
            "wrap_up_noticed": True,
            "messages": [*steering, notice],
        }
    if batching_hint_due(state, tool_rounds) and isinstance(latest, ToolMessage):
        logger.info("Turn batching hint", extra={"tool_rounds": tool_rounds})
        hinted = latest.model_copy(update={"content": f"{latest.content}{BATCHING_HINT}"})
        return {
            "tool_rounds": tool_rounds,
            "batching_hinted": True,
            "messages": [*steering, hinted],
        }
    return interjection


def _with_budgets(
    state: AgentState, tool_rounds: int, use_cache: bool, interjection: Update | None
) -> Update:
    """The loop detector's state, then a stop, the wrap-up
    notice, steering or self-correction - with the loop state in every result."""
    loops, warning = loop_state(state)
    state = cast("AgentState", {**state, **loops})
    result = _budget_update(state, tool_rounds, use_cache, interjection)
    if result is None:
        result = _self_correction(state, tool_rounds, use_cache)
    messages = list(cast("list[BaseMessage]", result.get("messages", [])))
    if warning and "final_answer" not in result:
        messages.append(_guidance(warning, use_cache))
    merged = {**loops, **result}
    if messages:
        merged["messages"] = messages
    return merged


def _self_correction(state: AgentState, tool_rounds: int, use_cache: bool) -> Update:
    """Retry or give-up guidance for the latest round's failures (none: reset)."""
    error_details, any_retriable = _latest_tool_errors(state["messages"])
    if not error_details:
        return {"tool_retries": 0, "tool_rounds": tool_rounds}
    return _error_guidance_update(
        state.get("tool_retries", 0), tool_rounds, error_details, any_retriable, use_cache
    )


def _latest_tool_errors(messages: list[BaseMessage]) -> tuple[list[str], bool]:
    """(error texts, any of them retriable) for the latest round's ToolMessages."""
    any_retriable = False
    error_details: list[str] = []
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            # Stop scanning once we hit the AIMessage that triggered the tools
            break
        if not isinstance(msg, ToolMessage):
            continue
        found = tool_message_error(msg)
        if found is not None:
            error_text, retriable = found
            any_retriable = any_retriable or retriable
            error_details.append(error_text)
    return error_details, any_retriable


def _error_guidance_update(
    tool_retries: int,
    tool_rounds: int,
    error_details: list[str],
    any_retriable: bool,
    use_cache: bool,
) -> Update:
    """Retry guidance while retries are left, give-up guidance after."""
    max_retries = Config.AGENT_MAX_TOOL_RETRIES
    new_retries = tool_retries + 1
    error_summary = "; ".join(error_details[:3])

    if not any_retriable:
        # Every failure is marked permanent (e.g. integration not configured) -
        # retrying with different arguments cannot help; go straight to give-up
        logger.info(
            "Tool error is non-retriable, skipping self-correction retries",
            extra={"errors": error_summary},
        )
        new_retries = max_retries + 1

    log_extra = {"retry": new_retries, "max_retries": max_retries, "errors": error_summary}
    if new_retries <= max_retries:
        logger.info("Tool error detected, providing self-correction guidance", extra=log_extra)
        content = (
            "The tool call failed with the following error. "
            "Analyze the error and try a different approach or different arguments. "
            "Do not repeat the same failing call.\n\n"
            f"Error: {error_summary}"
        )
    else:
        logger.warning("Tool error after max retries, providing give-up guidance", extra=log_extra)
        content = (
            "The tool has failed after multiple retries. "
            "Respond to the user explaining what happened and offer alternatives. "
            "Do not attempt to call the same tool again."
        )
    guidance = _guidance(content, use_cache)
    return {"tool_retries": new_retries, "tool_rounds": tool_rounds, "messages": [guidance]}


def check_tool_results(
    state: AgentState,
    use_cache: bool = False,
) -> Update:
    """After a tool round: steering, the turn budgets (src/agent/turn_budget.py)
    and the loop detector, then self-correction guidance if calls failed.

    After tools execute, this node checks for errors:
    - If errors found and retries < max: increment retries, add correction guidance
    - If errors found and retries >= max: increment retries, add give-up guidance
    - If no errors: reset retries to 0
    Always routes back to "chat" - the LLM decides whether to retry or respond.

    When use_cache is True, guidance is sent as HumanMessage (not SystemMessage)
    because LangChain drops mid-conversation SystemMessages in cached mode.
    """
    # Server-side Stop: the round that just finished is the last one
    raise_if_cancelled()

    # This node runs once per completed tool round, so it is the natural place
    # to count them. Each round re-invokes the model with the full accumulated
    # context, so unbounded rounds multiply input-token cost.
    tool_rounds = state.get("tool_rounds", 0) + 1

    update = _interjection_update(state, tool_rounds, use_cache)
    return _with_budgets(state, tool_rounds, use_cache, update)
