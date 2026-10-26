"""The graph's check_tool_results node: steering, round caps and self-correction.

Runs after every tool round and always routes back to chat; what it adds to
the state tells the model how to go on.
"""

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from src.agent import interjection
from src.agent.cancellation import raise_if_cancelled
from src.agent.graph_state import AgentState
from src.agent.round_cap import tool_round_cap
from src.agent.tools.context import get_conversation_context
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


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


def _interjection_update(
    state: AgentState, tool_rounds: int, use_cache: bool
) -> dict[str, Any] | None:
    """Mid-run steering the user sent while this turn was running, if any.

    Stored cross-worker in kv_store by the interject route. Checked FIRST so
    steering is never swallowed by the round-cap or nudge early-returns -
    redirecting the work takes priority over telling the model to wrap up.
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


def _round_pressure_update(
    tool_rounds: int, max_rounds: int, use_cache: bool
) -> dict[str, Any] | None:
    """The round-cap or soft-nudge guidance this round calls for, if any.

    Soft round cap: once hit, stop gathering and answer with what we have.
    Fires on every subsequent round too (tool_rounds stays >= cap), so the
    pressure escalates naturally if the model ignores the first nudge. The
    recursion limit remains the hard backstop.

    Soft efficiency nudge, well before the hard cap: overruns observed in
    evals came from drip-feeding single tool calls; a gentle reminder at
    this point cuts rounds without forcing a premature answer.
    """
    if max_rounds > 0 and tool_rounds >= max_rounds:
        logger.info(
            "Tool round cap reached, nudging model to answer",
            extra={"tool_rounds": tool_rounds, "max_rounds": max_rounds},
        )
        content = (
            f"You have run {tool_rounds} rounds of tool calls for this request. "
            "Stop calling tools now and answer the user with the information you "
            "already have. If you searched for something you could not find, say so "
            "and give your best answer with what is available. Do not issue more "
            "tool calls unless absolutely essential."
        )
    elif Config.AGENT_TOOL_ROUNDS_SOFT_NUDGE > 0 and (
        tool_rounds == Config.AGENT_TOOL_ROUNDS_SOFT_NUDGE
    ):
        content = (
            f"You have used {tool_rounds} tool rounds. Be efficient from here: "
            "consolidate remaining lookups (batch queries, prefer the research "
            "tool over separate fetches) and aim to answer within the next "
            "round or two."
        )
        logger.info("Soft round nudge injected", extra={"tool_rounds": tool_rounds})
    else:
        return None
    return {
        "tool_rounds": tool_rounds,
        "tool_retries": 0,
        "messages": [_guidance(content, use_cache)],
    }


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
) -> dict[str, Any]:
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
) -> dict[str, Any]:
    """Inspect tool results and provide self-correction guidance if errors occurred.

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

    tool_retries = state.get("tool_retries", 0)
    # This node runs once per completed tool round, so it is the natural place
    # to count them. Each round re-invokes the model with the full accumulated
    # context, so unbounded rounds multiply input-token cost.
    tool_rounds = state.get("tool_rounds", 0) + 1
    max_rounds = tool_round_cap()

    update = _interjection_update(state, tool_rounds, use_cache)
    if update is None:
        update = _round_pressure_update(tool_rounds, max_rounds, use_cache)
    if update is not None:
        return update

    error_details, any_retriable = _latest_tool_errors(state["messages"])
    if not error_details:
        if tool_retries > 0:
            logger.debug("Tool retries reset after successful execution")
        return {"tool_retries": 0, "tool_rounds": tool_rounds}
    return _error_guidance_update(
        tool_retries, tool_rounds, error_details, any_retriable, use_cache
    )
