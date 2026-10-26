"""The graph's chat node: one model call per round, with retries, Stop and fallback."""

from typing import Any

from langchain_core.callbacks import BaseCallbackManager
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.config import get_stream_writer

from src.agent.cancellation import CancelOnToken, raise_if_cancelled
from src.agent.chat_model import FallbackModel
from src.agent.graph_state import AgentState
from src.agent.retry import is_model_unavailable, with_retry
from src.agent.tool_result_aging import age_consumed_tool_messages
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
        primary = getattr(model, "model_name", "unknown")
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


def chat_node(
    state: AgentState,
    model: ChatGoogleGenerativeAI,
    use_cache: bool = False,
    config: RunnableConfig | None = None,
    fallback: FallbackModel | None = None,
) -> dict[str, Any]:
    """Process messages and generate a response.

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

    logger.debug(
        "Invoking LLM",
        extra={
            "message_count": len(messages),
            "model": model.model_name if hasattr(model, "model_name") else "unknown",
        },
    )
    response, fallback_name = _invoke_with_fallback(state, model, messages, config, fallback)
    if fallback_name and isinstance(response, AIMessage):
        response.response_metadata["model_fallback"] = fallback_name

    _log_response(response)

    if fallback_name:
        return {"messages": [response], "model_fallback": fallback_name}
    return {"messages": [response]}


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
