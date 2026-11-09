"""Turn budgets: what a turn may spend before it stops and answers.

Every turn is bounded by its running cost, its wall-clock time, a loop
detector and a round backstop (docs/superpowers/specs/2026-10-25-thorough-
turns-and-conversation-facts-design.md, "Turn budgets replace the round
cap"). The budget lives in the graph state, so each graph run - a chat turn,
or a subagent's run inside a tool call - has its own.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from src.agent.turn_usage import usage_tokens
from src.services.costs import calculate_token_cost

if TYPE_CHECKING:
    from langchain_core.messages import AIMessage, BaseMessage

    from src.agent.graph_state import AgentState


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
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return 0.0
    inp, out, cached = usage_tokens(usage)
    return calculate_token_cost(model_name, inp, out, cached_input_tokens=cached)
