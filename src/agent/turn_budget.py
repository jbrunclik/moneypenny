"""Turn budgets: what a turn may spend before it stops and answers.

Every turn is bounded by its running cost, its wall-clock time, a loop
detector and a round backstop (docs/superpowers/specs/2026-10-25-thorough-
turns-and-conversation-facts-design.md, "Turn budgets replace the round
cap"). The budget lives in the graph state, so each graph run - a chat turn,
or a subagent's run inside a tool call - has its own.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal

from src.agent.content import extract_text_content
from src.agent.round_cap import tool_round_cap
from src.config import Config
from src.services.costs import calculate_token_cost
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from langchain_core.messages import AIMessage, BaseMessage

    from src.agent.graph_state import AgentState

logger = get_logger(__name__)


def initial_state(messages: list[BaseMessage]) -> AgentState:
    """A graph run's input: its messages and a fresh budget (clock started)."""
    return {
        "messages": messages,
        "tool_retries": 0,
        "tool_rounds": 0,
        "turn_started_at": time.monotonic(),
        "turn_cost_usd": 0.0,
        "failed_calls": {},
    }


def call_cost_usd(response: AIMessage, model_name: str) -> float:
    """One model call's cost, priced with the model that answered it."""
    from src.agent.turn_usage import usage_tokens  # noqa: PLC0415 - cycle: turn_usage -> tool_round_check -> turn_budget

    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return 0.0
    inp, out, cached = usage_tokens(usage)
    return calculate_token_cost(model_name, inp, out, cached_input_tokens=cached)


StopReason = Literal["cost", "time", "rounds", "loop"]

# Appended to the latest tool result (results are read; prompt text is not)
WRAP_UP_NOTICE = "\n\n[Time is nearly up: finish with what you have in your next reply.]"
# Before the tools-off final call
FINAL_GUIDANCE = (
    "This turn has used its budget, so this is your last reply and tools are off. "
    "Answer the user with what you found. If something is still missing, say so and "
    "give your best answer with what is available. Then end with a short list of what "
    "you would do next if you could continue - the concrete remaining steps - so the "
    "user can tell you to go on."
)


def elapsed_s(state: AgentState) -> float:
    """Seconds since the run's budget started (0 when it has none)."""
    started = state.get("turn_started_at")
    return 0.0 if started is None else time.monotonic() - started


def budget_stop(state: AgentState, tool_rounds: int) -> StopReason | None:
    """The limit this turn just hit, if any: cost, then time, then rounds."""
    if state.get("turn_cost_usd", 0.0) >= Config.TURN_COST_LIMIT_USD:
        return "cost"
    if elapsed_s(state) >= Config.TURN_TIME_BUDGET_SECONDS:
        return "time"
    cap = tool_round_cap()
    if cap > 0 and tool_rounds >= cap:
        return "rounds"
    return None


def wrap_up_due(state: AgentState) -> bool:
    """The one wrap-up notice is due (past the fraction, not sent yet)."""
    if state.get("wrap_up_noticed"):
        return False
    budget = Config.TURN_TIME_BUDGET_SECONDS
    return elapsed_s(state) >= Config.TURN_WRAP_UP_FRACTION * budget


def log_stop(reason: StopReason, state: AgentState, tool_rounds: int) -> None:
    """One line per stop: the regular review reads these (rule A8)."""
    logger.info(
        "Turn budget stop",
        extra={
            "reason": reason,
            "tool_rounds": tool_rounds,
            "elapsed_s": round(elapsed_s(state), 1),
            "cost_usd": round(state.get("turn_cost_usd", 0.0), 4),
        },
    )


# An empty last reply still tells the user where things stand
FALLBACK_LINE = "I stopped before finishing - say *continue* and I'll pick up from here."
_GUIDANCE_PREFIX = "[SYSTEM GUIDANCE]"


def final_reply(response: AIMessage, history: list[BaseMessage]) -> AIMessage:
    """The turn's last reply: never a tool call (tools are off), never empty."""
    reply = response
    if response.tool_calls:
        logger.info(
            "Turn final answer dropped tool calls",
            extra={"tools": [c["name"] for c in response.tool_calls]},
        )
        reply = response.model_copy(update={"tool_calls": [], "invalid_tool_calls": []})
    if extract_text_content(reply.content).strip():
        return reply
    earlier = _earlier_text(history)
    text = f"{earlier}\n\n{FALLBACK_LINE}" if earlier else FALLBACK_LINE
    return reply.model_copy(update={"content": text})


def _earlier_text(history: list[BaseMessage]) -> str:
    """The model's last non-empty text in this turn (back to the user's message)."""
    from langchain_core.messages import AIMessage, HumanMessage  # noqa: PLC0415 - typing-only above

    for message in reversed(history):
        if isinstance(message, HumanMessage) and not str(message.content).startswith(
            _GUIDANCE_PREFIX
        ):
            return ""
        if isinstance(message, AIMessage) and (
            text := extract_text_content(message.content).strip()
        ):
            return text
    return ""
