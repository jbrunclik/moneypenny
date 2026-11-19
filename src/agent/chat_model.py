"""Gemini chat models for the graph: creation, tool binding and the fallback tier."""

from collections.abc import Callable
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI

from src.agent.tools import get_available_tools
from src.config import Config

FallbackModel = Callable[[], tuple[str, ChatGoogleGenerativeAI]]


def _model_kwargs(
    model_name: str,
    include_thoughts: bool,
    temperature: float | None,
    thinking_level: str | None,
) -> dict[str, Any]:
    """ChatGoogleGenerativeAI arguments shared by the turn's model and its fallback."""
    # No convert_system_message_to_human: deprecated, and on langchain-google-genai
    # 4.x it folded the system prompt into the first HumanMessage instead of using
    # Gemini's native systemInstruction field (plus a DeprecationWarning per request).
    # Native handling: SystemMessage at position 0 becomes systemInstruction, and
    # mid-conversation SystemMessages are merged into it - which changes the request
    # prefix, hence mid-turn guidance goes as a wrapped HumanMessage.
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
    thinking_level: str | None = None,
) -> ChatGoogleGenerativeAI:
    """Create a Gemini chat model, optionally with tools bound.

    Args:
        model_name: The Gemini model to use
        with_tools: Whether to bind tools to the model
        include_thoughts: Whether to include thinking/reasoning summaries in responses
        tools: Custom list of tools to bind (defaults to get_available_tools())
        temperature: Override for model temperature (defaults to Config.GEMINI_DEFAULT_TEMPERATURE)
        thinking_level: Overrides the model's configured thinking_level (the
            freshness gate runs easy turns lighter).
    """
    kwargs = _model_kwargs(model_name, include_thoughts, temperature, thinking_level)

    model = ChatGoogleGenerativeAI(**kwargs, timeout=Config.GEMINI_REQUEST_TIMEOUT_SECONDS)

    active_tools = tools if tools is not None else get_available_tools()
    if with_tools and active_tools:
        return model.bind_tools(active_tools)  # type: ignore[return-value]

    return model


def other_model_tier(model_name: str) -> str | None:
    """The model a turn falls back to when this one fails ("fallback" on its
    MODELS entry), or None for a model that is not user-selectable."""
    return Config.MODELS.get(model_name, {}).get("fallback")


def fallback_model_factory(
    model_name: str, with_tools: bool, include_thoughts: bool, tools: list[Any]
) -> FallbackModel | None:
    """Builds the other tier's model on first use, with the same tools."""
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
