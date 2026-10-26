"""Shrink tool results the model already consumed earlier in the turn."""

from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from src.agent.tools.metadata import EXTRACT_ONLY_TOOL_NAMES
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

AGED_MULTIMODAL_STUB = (
    "[The binary content returned by this tool was shown to you in an earlier "
    "step of this turn and has been removed to save tokens. Use what you "
    "already extracted from it; call the tool again only if you truly need it.]"
)

AGED_TRUNCATION_MARKER = "\n[...result truncated after you already processed it]"


def _aged_copy(msg: ToolMessage, max_chars: int, log: Callable[..., Any]) -> ToolMessage | None:
    """The shrunken copy of a consumed result, or None when it is small enough."""
    if isinstance(msg.content, list):
        log("Aged multimodal tool result", extra={"tool": getattr(msg, "name", None)})
        return msg.model_copy(update={"content": AGED_MULTIMODAL_STUB})
    if isinstance(msg.content, str) and len(msg.content) > max_chars:
        log(
            "Aged oversized tool result",
            extra={"tool": getattr(msg, "name", None), "chars_before": len(msg.content)},
        )
        aged = msg.content[:max_chars] + AGED_TRUNCATION_MARKER
        return msg.model_copy(update={"content": aged})
    return None


def age_consumed_tool_messages(messages: list[BaseMessage]) -> None:
    """Shrink tool results the model has already consumed once.

    Within a turn, every ToolMessage is re-sent on each subsequent LLM call.
    ToolMessages that answer the LATEST tool-calling AIMessage are fresh (the
    model has not seen them yet) and must pass through untouched - especially
    multimodal content (fetched PDFs/images, screenshots) which the model
    needs to analyze exactly once. Anything older has already been consumed:
    multimodal content becomes a stub and long text is truncated.

    Aged results are copies put into `messages` (the list sent to the model):
    the turn's state keeps the full results, which the source chips and the
    grounding check read after the turn (Oct 2026: aging a research JSON in
    place left it unparseable, and 52 of 156 research turns in 30 days lost
    their pages).

    A round that only set the title consumed nothing: the model still has to
    answer from the results before it (Oct 2026: 48 turns in 14 days lost
    their research this way and answered with no sources).
    """
    max_chars = Config.AGENT_AGED_TOOL_RESULT_MAX_CHARS
    if max_chars <= 0:
        return

    rounds = [
        i
        for i, msg in enumerate(messages)
        if isinstance(msg, AIMessage)
        and msg.tool_calls
        and not all(tc["name"] in EXTRACT_ONLY_TOOL_NAMES for tc in msg.tool_calls)
    ]
    last_tool_call_idx = rounds[-1] if rounds else len(messages)
    # Results before the previous round were aged (and logged) by an earlier call
    first_new_idx = rounds[-2] if len(rounds) > 1 else -1

    for i, msg in enumerate(messages[:last_tool_call_idx]):
        # A loaded skill is instructions for the whole turn, not consumed data:
        # truncating it would drop exactly the guidance later rounds need
        if not isinstance(msg, ToolMessage) or msg.name == "load_skill":
            continue
        log = logger.info if i > first_new_idx else logger.debug
        aged = _aged_copy(msg, max_chars, log)
        if aged is not None:
            messages[i] = aged
