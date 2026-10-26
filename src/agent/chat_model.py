"""Gemini chat models for the graph: creation, tool binding and the fallback tier."""

from collections.abc import Callable
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI

from src.agent.tools import get_available_tools
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

FallbackModel = Callable[[], tuple[str, ChatGoogleGenerativeAI]]


def _model_kwargs(
    model_name: str,
    include_thoughts: bool,
    temperature: float | None,
    thinking_level: str | None,
) -> dict[str, Any]:
    """ChatGoogleGenerativeAI arguments shared by the cached and uncached model."""
    # No convert_system_message_to_human: deprecated, and on langchain-google-genai
    # 4.x it folded the system prompt into the first HumanMessage instead of using
    # Gemini's native systemInstruction field (plus a DeprecationWarning per request).
    # Native handling: SystemMessage at position 0 becomes systemInstruction, and
    # mid-conversation SystemMessages are merged into it (dropped only when there is
    # no position-0 SystemMessage - hence the HumanMessage guidance in cached mode).
    kwargs: dict[str, Any] = {
        "model": model_name,
        "google_api_key": Config.GEMINI_API_KEY,
        "max_retries": Config.AGENT_MODEL_SDK_MAX_RETRIES,
        "temperature": temperature
        if temperature is not None
        else Config.GEMINI_DEFAULT_TEMPERATURE,
        "include_thoughts": include_thoughts,
    }

    # Optional per-model reasoning depth (Gemini 3+ thinking_level). Unset =
    # API default. Configured via the "thinking_level" key on MODELS entries.
    thinking_level = thinking_level or Config.MODELS.get(model_name, {}).get("thinking_level")
    if thinking_level:
        kwargs["thinking_level"] = thinking_level
    return kwargs


def create_chat_model(
    model_name: str,
    with_tools: bool = True,
    include_thoughts: bool = False,
    tools: list[Any] | None = None,
    temperature: float | None = None,
    cached_content: str | None = None,
    thinking_level: str | None = None,
) -> ChatGoogleGenerativeAI:
    """Create a Gemini chat model, optionally with tools bound.

    Args:
        model_name: The Gemini model to use
        with_tools: Whether to bind tools to the model
        include_thoughts: Whether to include thinking/reasoning summaries in responses
        tools: Custom list of tools to bind (defaults to get_available_tools())
        temperature: Override for model temperature (defaults to Config.GEMINI_DEFAULT_TEMPERATURE)
        cached_content: Gemini cached content name. When provided, tools are NOT bound
            (they're already in the cache) and system_instruction is omitted.
        thinking_level: Overrides the model's configured thinking_level (the
            freshness gate runs easy turns lighter).
    """
    kwargs = _model_kwargs(model_name, include_thoughts, temperature, thinking_level)

    if cached_content:
        kwargs["cached_content"] = cached_content
        # Do NOT bind_tools when using cached_content — tools are in the cache
        logger.info(
            "Creating model with cached content",
            extra={"cached_content": cached_content, "model": model_name},
        )
        return ChatGoogleGenerativeAI(**kwargs, timeout=Config.GEMINI_REQUEST_TIMEOUT_SECONDS)

    model = ChatGoogleGenerativeAI(**kwargs, timeout=Config.GEMINI_REQUEST_TIMEOUT_SECONDS)

    active_tools = tools if tools is not None else get_available_tools()
    if with_tools and active_tools:
        return model.bind_tools(active_tools)  # type: ignore[return-value]

    return model


def other_model_tier(model_name: str) -> str | None:
    """The other user-selectable model (Fast <-> Advanced), if there is one."""
    others = [name for name in Config.MODELS if name != model_name]
    return others[0] if model_name in Config.MODELS and others else None


def fallback_model_factory(
    model_name: str, with_tools: bool, include_thoughts: bool, tools: list[Any]
) -> FallbackModel | None:
    """Builds the other tier's model on first use: same tools, no context cache
    (the cache is per (profile, model))."""
    other = other_model_tier(model_name)
    if other is None:
        return None
    built: list[ChatGoogleGenerativeAI] = []

    def factory() -> tuple[str, ChatGoogleGenerativeAI]:
        if not built:
            built.append(
                create_chat_model(
                    other, with_tools=with_tools, include_thoughts=include_thoughts, tools=tools
                )
            )
        return other, built[0]

    return factory
