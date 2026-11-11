"""The graph's chat node: one model call per round, with retries, Stop and fallback."""

from typing import Any

from langchain_core.callbacks import BaseCallbackManager
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.config import get_stream_writer

from src.agent.cancellation import CancelOnToken, raise_if_cancelled
from src.agent.chat_model import FallbackModel, create_chat_model
from src.agent.content import extract_text_content
from src.agent.graph_state import AgentState
from src.agent.retry import is_model_unavailable, with_retry
from src.agent.tool_result_aging import age_consumed_tool_messages
from src.agent.turn_budget import (
    call_cost_usd,
    fallback_line,
    final_guidance,
    final_reply,
    final_transcript,
    model_view,
)
from src.agent.turn_usage import record_model_usage
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _emit_retry_status(error: Exception, attempt: int) -> None:
    """Tell the stream a transient model error is being retried.

    The backoff can add up to ~70 s per model call; without a status the turn
    looked hung. Written to LangGraph's custom stream (forwarded as a `retry`
    SSE event); outside a streaming run there is no writer and this is a no-op.
    """
    try:
        writer = get_stream_writer()
        writer(
            {
                "type": "retry",
                "attempt": attempt + 1,
                "max_retries": Config.AGENT_MAX_RETRIES,
            }
        )
    except Exception:
        logger.debug("No stream writer for retry status", exc_info=True)


def _emit_model_fallback(from_model: str, to_model: str) -> None:
    """Tell the stream the other model tier is answering (client shows a note)."""
    try:
        get_stream_writer()({"type": "model_fallback", "from": from_model, "to": to_model})
    except Exception:
        logger.debug("No stream writer for model fallback", exc_info=True)


def _invoke_with_fallback(
    state: AgentState,
    model: ChatGoogleGenerativeAI,
    messages: list[BaseMessage],
    config: RunnableConfig | None,
    fallback: FallbackModel | None,
    primary: str,
) -> tuple[BaseMessage, str | None]:
    """The model's reply, or the other tier's when the model is down (503).

    Once a turn fell back it stays on the fallback: every round would
    otherwise first wait for the dead model again.
    """
    invoke = with_retry(_invoke_model, on_retry=_emit_retry_status)
    if state.get("model_fallback") and fallback:
        name, backup = fallback()
        return invoke(backup, messages, config), name
    try:
        return invoke(model, messages, config), None
    except Exception as error:
        if fallback is None or not is_model_unavailable(error):
            raise
        name, backup = fallback()
        logger.warning(
            "Model unavailable, falling back", extra={"model": primary, "fallback": name}
        )
        _emit_model_fallback(primary, name)
        return invoke(backup, messages, config), name


def _log_response(response: BaseMessage) -> None:
    """Log the reply's tool calls (or that it has none) and its usage metadata."""
    if isinstance(response, AIMessage) and response.tool_calls:
        tool_names = [tc.get("name", "unknown") for tc in response.tool_calls]
        logger.info(
            "LLM requested tool calls",
            extra={"tool_calls": tool_names, "count": len(response.tool_calls)},
        )
    else:
        logger.debug("LLM response received", extra={"has_content": bool(response.content)})

    # Note: usage_metadata is a direct attribute, not in response_metadata
    if not isinstance(response, AIMessage):
        return
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        usage = response.usage_metadata
        logger.debug(
            "Usage metadata captured",
            extra={
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        )
    else:
        logger.debug("No usage_metadata attribute found on AIMessage")


def _tell_the_stream(
    response: AIMessage, reason: str, facts: str | None, answered: bool = False
) -> None:
    """Streaming saves the streamed chunks, not final_reply's result: tell the
    processor why the turn stopped, which tool calls it drops and the line it
    adds to an empty reply (none when the tools-off retry answered)."""
    empty = not answered and not extract_text_content(response.content).strip()
    get_stream_writer()(
        {
            "type": "turn_stop",
            "reason": reason,
            "dropped": [c["id"] for c in response.tool_calls if c["id"]],
            "fallback": fallback_line(facts) if empty else None,
        }
    )


def _answer_without_tools(
    messages: list[BaseMessage], facts: str, model_name: str, config: RunnableConfig | None
) -> AIMessage | None:
    """The final reply from a model that has no tools at all.

    Gemini's context cache carries the tool declarations, so in cached mode
    "tools are off" is only an instruction - and the Daily Briefing's final
    round asked for one more tool, leaving the user an empty reply (Nov 11
    2026). The turn so far goes in as plain text: a model without tools can't
    take tool calls and results.
    """
    logger.info("Turn final answer retried without tools", extra={"model": model_name})
    plain = create_chat_model(model_name, with_tools=False)
    prompt = [SystemMessage(content=final_guidance(facts)), *final_transcript(messages)]
    try:
        reply = _invoke_model(plain, prompt, config)
    except Exception:
        logger.exception("Turn final answer without tools failed")
        return None
    return reply if isinstance(reply, AIMessage) else None


def chat_node(
    state: AgentState,
    model: ChatGoogleGenerativeAI,
    use_cache: bool = False,
    config: RunnableConfig | None = None,
    fallback: FallbackModel | None = None,
    model_name: str = "unknown",
) -> dict[str, Any]:
    """Process messages and generate a response.

    model_name names the turn's model (the Gemini client has no attribute for
    it): the turn's cost is priced with it, or with the fallback that answered.

    use_cache is unused here but kept in the signature for parity with
    check_tool_results (both are bound via lambda in create_chat_graph and
    the flag documents which mode the graph was built for).
    """
    # Server-side Stop: never start another model call once Stop was pressed
    raise_if_cancelled()

    messages = list(state["messages"])

    # Shrink tool results the model already consumed in this turn (they are
    # otherwise re-sent in full on every loop iteration)
    age_consumed_tool_messages(messages)
    # Notes on tool results (wrap-up, batching hint, unchanged repeat) reach
    # only the model; the state keeps the results parseable
    messages = model_view(messages)

    logger.debug(
        "Invoking LLM",
        extra={
            "message_count": len(messages),
            "model": model_name,
        },
    )
    response, fallback_name = _invoke_with_fallback(
        state, model, messages, config, fallback, model_name
    )
    if fallback_name and isinstance(response, AIMessage):
        response.response_metadata["model_fallback"] = fallback_name

    _log_response(response)
    # The turn's running cost, priced with the model that answered
    answering = fallback_name or model_name
    cost = state.get("turn_cost_usd", 0.0)
    if isinstance(response, AIMessage):
        cost += call_cost_usd(response, answering)

    # Turn budgets: after a stop this is the last reply - no tool calls, never empty
    reason = state.get("final_answer")
    if reason and isinstance(response, AIMessage):
        response, cost = _final_answer(response, state, messages, config, answering, cost)
    update: dict[str, object] = {"messages": [response], "turn_cost_usd": cost}
    if fallback_name:
        update["model_fallback"] = fallback_name
    return update


def _final_answer(
    response: AIMessage,
    state: AgentState,
    messages: list[BaseMessage],
    config: RunnableConfig | None,
    model_name: str,
    cost: float,
) -> tuple[AIMessage, float]:
    """The stopped turn's last reply, and the turn's cost including any retry."""
    reason = str(state.get("final_answer"))
    facts = state.get("stop_facts")
    text = extract_text_content(response.content).strip()
    retry = None
    if response.tool_calls and not text:
        retry = _answer_without_tools(messages, facts or reason, model_name, config)
        if retry is not None:
            cost += call_cost_usd(retry, model_name)
    answered = retry is not None and bool(extract_text_content(retry.content).strip())
    _tell_the_stream(response, reason, facts, answered)
    if answered and retry is not None:
        merged = retry.model_copy(update={"response_metadata": {**retry.response_metadata}})
        return final_reply(merged, messages, reason, facts), cost
    return final_reply(response, messages, reason, facts), cost


def _invoke_model(
    model: ChatGoogleGenerativeAI, messages: list[BaseMessage], config: RunnableConfig | None
) -> BaseMessage:
    """One model call that Stop can abort mid-stream (checked per attempt and per token)."""
    raise_if_cancelled()
    response = model.invoke(messages, config=_with_cancel_callback(config))
    record_model_usage(response)
    return response


def _with_cancel_callback(config: RunnableConfig | None) -> RunnableConfig:
    """The node's config plus CancelOnToken, KEEPING the inherited callbacks.

    Replacing them (config={"callbacks": [...]} or with_config) drops
    LangGraph's streaming handler: the model then answers without streaming
    and no tokens reach the client.
    """
    config = config or {}
    inherited = config.get("callbacks")
    handler = CancelOnToken()
    if isinstance(inherited, BaseCallbackManager):
        callbacks: Any = inherited.copy()
        callbacks.add_handler(handler, inherit=True)
    else:
        callbacks = [*(inherited or []), handler]
    return {**config, "callbacks": callbacks}
