"""Per-turn token usage and tool telemetry for ChatAgent turns.

Feeds the usage_info dict every ChatAgent entry point returns (cost tracking
and the per-turn observability columns on message_costs).
"""

import time
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage

from src.agent.tool_round_check import tool_message_error
from src.agent.tools.turn_usage import get_tool_call_count
from src.utils.logging import get_logger

logger = get_logger(__name__)


def usage_tokens(usage: Mapping[str, Any]) -> tuple[int, int, int]:
    """Extract (input, output, cache_read) from a usage_metadata dict.

    cache_read is the subset of input_tokens served from Gemini's context
    cache (billed at the discounted cached_input rate). Streaming chunks are
    delta-encoded - input_tokens and cache_read arrive once per LLM call -
    so summing across chunks/messages is correct.
    """
    details = usage.get("input_token_details")
    cache_read = details.get("cache_read", 0) if isinstance(details, dict) else 0
    return usage.get("input_tokens", 0), usage.get("output_tokens", 0), cache_read


def tool_telemetry(messages: Iterable[BaseMessage]) -> tuple[int, int]:
    """Count (tool_rounds, tool_call_count) over a turn's messages/chunks.

    tool_rounds: distinct LLM responses (by message id) that requested tool
    calls. This is the round-multiplication multiplier - each one re-invokes
    the model with the accumulated context, so it drives input-token cost far
    more than the size of any single tool payload.
    tool_call_count: number of tool executions (ToolMessages) in the turn.

    Streaming chunks of one response share an id (verified for Gemini), so
    deduping by id counts each round once however many chunks carried the
    tool call. Full messages (batch path) each have their own id too.
    """
    round_ids: set[Any] = set()
    tool_execs = 0
    for m in messages:
        if isinstance(m, ToolMessage):
            tool_execs += 1
        elif isinstance(m, AIMessage | AIMessageChunk) and (
            getattr(m, "tool_calls", None) or getattr(m, "tool_call_chunks", None)
        ):
            round_ids.add(m.id or id(m))
    return len(round_ids), tool_execs


def tool_usage_details(messages: Iterable[BaseMessage]) -> tuple[list[str], int]:
    """(sorted unique tool names, error count) over a turn's ToolMessages.

    Errors use the same structural detection as self-correction
    (tool_round_check.tool_message_error): status=="error" or a JSON error envelope.
    Feeds the per-turn observability columns on message_costs.
    """
    names: set[str] = set()
    errors = 0
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        if message.name:
            names.add(message.name)
        if tool_message_error(message) is not None:
            errors += 1
    return sorted(names), errors


@dataclass
class TokenTotals:
    """Running input/output/cache-read token totals for one turn."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    def add_from(self, message: BaseMessage) -> tuple[int, int, int] | None:
        """Add a message's usage_metadata; returns the added counts, or None.

        Messages without usage (or with zero input and output) add nothing.
        """
        if not (hasattr(message, "usage_metadata") and message.usage_metadata):
            return None
        usage = message.usage_metadata
        if not isinstance(usage, dict):
            return None
        input_tokens, output_tokens, cache_read = usage_tokens(usage)
        if input_tokens <= 0 and output_tokens <= 0:
            return None
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cached_tokens += cache_read
        return input_tokens, output_tokens, cache_read

    @property
    def any(self) -> bool:
        """True once any input or output tokens were recorded."""
        return self.input_tokens > 0 or self.output_tokens > 0


# Where a turn's model calls are timed: the graph config's configurable (a
# delegate's or a deep-research subagent's own graph is not counted)
MODEL_TIMING_KEY = "model_timing"


def _ms_since(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


@dataclass
class ModelTiming:
    """Wall time of a turn's model calls (chat_node._invoke_model)."""

    calls: int = 0
    ms: int = 0
    finish_reason: str | None = None
    # The longest stretch inside a streamed call with no chunk (None: no call
    # streamed) - decides whether a stall watchdog is needed (Nov 15 2026)
    max_silence_ms: int | None = None
    # Whose turn it is (the prefix telemetry's same-user flag) and one entry
    # per call: tokens, ms, prefix, gap since it was last sent (Nov 15 2026)
    user_id: str | None = None
    entries: list[dict[str, object]] = field(default_factory=list)

    def record(
        self, started: float, response: BaseMessage | None, silence_s: float | None = None
    ) -> None:
        """One call that began at ``started`` (monotonic) and ended now, with
        its longest silence when it streamed."""
        self.calls += 1
        self.ms += _ms_since(started)
        if silence_s is not None:
            self.max_silence_ms = max(self.max_silence_ms or 0, round(silence_s * 1000))
        reason = response.response_metadata.get("finish_reason") if response else None
        if reason:
            self.finish_reason = str(reason)


def _configurable(config: Mapping[str, object] | None) -> Mapping[str, object]:
    configurable = (config or {}).get("configurable")
    return configurable if isinstance(configurable, Mapping) else {}


def with_model_timing(config: Mapping[str, object], timing: ModelTiming) -> dict[str, object]:
    """The graph config, with ``timing`` collecting its model calls."""
    return {**config, "configurable": {**_configurable(config), MODEL_TIMING_KEY: timing}}


def model_timing_of(config: Mapping[str, object] | None) -> ModelTiming | None:
    """The turn's model-call clock in a node's config, if it has one."""
    timing = _configurable(config).get(MODEL_TIMING_KEY)
    return timing if isinstance(timing, ModelTiming) else None


class _GateDecision(Protocol):
    @property
    def lookup(self) -> bool: ...
    @property
    def thinking(self) -> str | None: ...
    @property
    def call_ms(self) -> int | None: ...


@dataclass
class TurnClock:
    """Where one turn's time went (Nov 15 2026 audit: nothing measured it).

    ``started`` is when the agent took the turn, before the prompt is built;
    the gate and its lookup run before the graph, the model calls inside it.
    """

    started: float = field(default_factory=time.monotonic)
    gate_ms: int | None = None
    lookup_ms: int | None = None
    model: ModelTiming = field(default_factory=ModelTiming)

    def gate_done(self, started: float) -> None:
        self.gate_ms = _ms_since(started)

    def lookup_done(self, started: float) -> None:
        self.lookup_ms = _ms_since(started)

    def timing(
        self, first_token_at: float | None, decision: _GateDecision | None
    ) -> dict[str, object]:
        """usage_info["timing"] (message_costs.turn_timing); unmeasured parts left out."""
        first_token_ms = (
            round((first_token_at - self.started) * 1000) if first_token_at is not None else None
        )
        timing: dict[str, object] = {
            "first_token_ms": first_token_ms,
            "gate_ms": self.gate_ms,
            "lookup_ms": self.lookup_ms,
            "model_ms": self.model.ms,
            "model_calls": self.model.calls,
            "finish_reason": self.model.finish_reason,
            "max_silence_ms": self.model.max_silence_ms,
            "calls": self.model.entries or None,
            # Lookups of a condensed memory's full text (Nov 15 2026)
            "memory_fetches": get_tool_call_count("memory_fetch") or None,
        }
        if decision is not None:
            timing["gate_lookup"] = bool(decision.lookup)
            timing["thinking"] = decision.thinking
            # The call's own time; gate_ms is what the turn waited for it
            # (less when the route started it early, Nov 16 2026)
            timing["gate_call_ms"] = decision.call_ms
        return {k: v for k, v in timing.items() if v is not None}


def build_usage_info(
    totals: TokenTotals,
    messages: list[BaseMessage],
    duration_ms: int,
    stopped_by: str | None = None,
) -> dict[str, Any]:
    """The usage_info dict returned with every ChatAgent turn.

    stopped_by: the turn-budget stop the stream reported; a batch turn's
    final reply carries it in its response_metadata instead.
    """
    tool_rounds, tool_call_count = tool_telemetry(messages)
    stopped = stopped_by or next(
        (
            str(m.response_metadata["turn_stop"])
            for m in messages
            if isinstance(m, AIMessage) and m.response_metadata.get("turn_stop")
        ),
        None,
    )
    tools_used, tool_errors = tool_usage_details(messages)
    usage: dict[str, Any] = {
        "input_tokens": totals.input_tokens,
        "output_tokens": totals.output_tokens,
        "cached_input_tokens": totals.cached_tokens,
        "tool_rounds": tool_rounds,
        "tool_call_count": tool_call_count,
        "duration_ms": duration_ms,
        "tools_used": tools_used,
        "tool_errors": tool_errors,
        "stopped_by": stopped,
    }
    # The other model tier answered (chat_node.chat_node): price the turn at it
    fallback = next(
        (
            m.response_metadata["model_fallback"]
            for m in messages
            if isinstance(m, AIMessage) and m.response_metadata.get("model_fallback")
        ),
        None,
    )
    if fallback:
        usage["model_fallback"] = fallback
    return usage


def batch_usage_info(result_messages: list[BaseMessage], duration_ms: int) -> dict[str, Any]:
    """usage_info for a non-streamed turn, summed over its AIMessages."""
    totals = TokenTotals()
    for msg in result_messages:
        if isinstance(msg, AIMessage):
            added = totals.add_from(msg)
            if added:
                input_tokens, output_tokens, cache_read = added
                logger.debug(
                    "Found usage metadata in AIMessage",
                    extra={
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cache_read": cache_read,
                    },
                )

    usage_info = build_usage_info(totals, result_messages, duration_ms)

    if totals.any:
        logger.debug(
            "Usage metadata aggregated",
            extra={
                "input_tokens": totals.input_tokens,
                "output_tokens": totals.output_tokens,
                "cached_input_tokens": totals.cached_tokens,
                "tool_rounds": usage_info["tool_rounds"],
                "tool_call_count": usage_info["tool_call_count"],
            },
        )
    return usage_info


# Spend recorded per model call, for turns that may be cut before they return
# their usage (deep-research subagents). Contextvars reach graph nodes.
_model_usage: ContextVar[TokenTotals | None] = ContextVar("model_usage", default=None)


@contextmanager
def collecting_model_usage(totals: TokenTotals) -> Iterator[TokenTotals]:
    """Add every model call's tokens made inside the block to totals."""
    token = _model_usage.set(totals)
    try:
        yield totals
    finally:
        _model_usage.reset(token)


def record_model_usage(message: BaseMessage) -> None:
    """Called after each model call; a no-op outside collecting_model_usage."""
    totals = _model_usage.get()
    if totals is not None:
        totals.add_from(message)
