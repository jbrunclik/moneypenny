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
    from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

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
# Once, mid-hunt: batch independent lookups - and no hurry to answer
BATCHING_HINT = (
    "\n\n[Tip: independent lookups can go into one round - several queries in one call "
    "(research and web_search take a list). Take the time the task needs.]"
)
# Before the tools-off final call; {facts} is stop_facts(). Nov 11 2026: the
# user asked to be told why a reply stopped and what Continue would change
FINAL_GUIDANCE = (
    "This turn has used its budget, so this is your last reply and tools are off - "
    "do not call any tool. It stopped at {facts}.\n"
    "1. Answer the user with what you found. If something is still missing, say so and "
    "give your best answer with what is available.\n"
    "2. Then, in one short sentence, tell the user why you stopped (the limit above, in "
    "plain words) and, if you can tell, what used it up (for example repeated lookups "
    "or very large results).\n"
    "3. End with what you would do if the user says continue: the concrete remaining "
    "steps, and what you would do differently - what you would reuse from above "
    "instead of fetching again, and what you would skip or narrow down."
)


def final_guidance(facts: str) -> str:
    """The tools-off final call's instruction, naming the limit that stopped it."""
    return FINAL_GUIDANCE.format(facts=facts)


def stop_facts(reason: StopReason, state: AgentState, tool_rounds: int) -> str:
    """The stop in plain words, for the model and for the fallback line."""
    used = f"after {tool_rounds} tool rounds in {round(elapsed_s(state))} s"
    spent = f"${state.get('turn_cost_usd', 0.0):.3f} spent"
    limits: dict[str, str] = {
        "cost": f"the ${Config.TURN_COST_LIMIT_USD:.2f} cost limit for one reply",
        "time": f"the {Config.TURN_TIME_BUDGET_SECONDS:.0f} s time limit for one reply",
        "rounds": f"the {tool_round_cap()}-round limit for one reply",
        "loop": "a tool call that kept failing",
    }
    return f"{limits[reason]}, {used} ({spent})"


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
    # A blocked call tried again twice: the model is stuck on it
    if max(state.get("failed_calls", {}).values(), default=0) >= Config.TURN_LOOP_BLOCK_AFTER + 2:
        return "loop"
    return None


def wrap_up_due(state: AgentState) -> bool:
    """The one wrap-up notice is due (past the fraction, not sent yet)."""
    if state.get("wrap_up_noticed"):
        return False
    budget = Config.TURN_TIME_BUDGET_SECONDS
    return elapsed_s(state) >= Config.TURN_WRAP_UP_FRACTION * budget


def batching_hint_due(state: AgentState, tool_rounds: int) -> bool:
    """The one batching hint is due (this round, not sent yet)."""
    at = Config.TURN_BATCHING_HINT_ROUND
    return at > 0 and tool_rounds == at and not state.get("batching_hinted")


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


def fallback_line(facts: str | None) -> str:
    """The app's own line for an empty last reply, naming the limit when known."""
    if not facts:
        return FALLBACK_LINE
    return (
        f"I stopped before finishing: I reached {facts}. Say *continue* and I'll pick up from here."
    )


_GUIDANCE_PREFIX = "[SYSTEM GUIDANCE]"

# A note for the model on a tool result, kept beside the content: the stored
# result stays parseable for source chips, artifacts and grounding (Oct 2026:
# a research JSON with text appended lost its pages)
_NOTE_KEY = "turn_note"


def with_note(message: ToolMessage, note: str) -> ToolMessage:
    """The tool result with a note for the model (added to any earlier note)."""
    kwargs = dict(message.additional_kwargs)
    kwargs[_NOTE_KEY] = f"{kwargs.get(_NOTE_KEY, '')}{note}"
    return message.model_copy(update={"additional_kwargs": kwargs})


def model_view(messages: list[BaseMessage]) -> list[BaseMessage]:
    """The messages as the model sees them: notes appended to their results."""
    from langchain_core.messages import ToolMessage  # noqa: PLC0415 - typing-only above

    out: list[BaseMessage] = []
    for message in messages:
        note = message.additional_kwargs.get(_NOTE_KEY)
        if isinstance(message, ToolMessage) and note and isinstance(message.content, str):
            kwargs = {k: v for k, v in message.additional_kwargs.items() if k != _NOTE_KEY}
            message = message.model_copy(
                update={"content": f"{message.content}{note}", "additional_kwargs": kwargs}
            )
        out.append(message)
    return out


def final_reply(
    response: AIMessage, history: list[BaseMessage], reason: str, facts: str | None = None
) -> AIMessage:
    """The turn's last reply: never a tool call (tools are off), never empty,
    marked with why the turn stopped (turn_usage reads it)."""
    reply = response.model_copy(
        update={"response_metadata": {**response.response_metadata, "turn_stop": reason}}
    )
    if response.tool_calls:
        logger.info(
            "Turn final answer dropped tool calls",
            extra={"tools": [c["name"] for c in response.tool_calls]},
        )
        reply = reply.model_copy(update={"tool_calls": [], "invalid_tool_calls": []})
    if extract_text_content(reply.content).strip():
        return reply
    earlier = _earlier_text(history)
    line = fallback_line(facts)
    text = f"{earlier}\n\n{line}" if earlier else line
    return reply.model_copy(update={"content": text})


# The tools-off retry's transcript: enough of each result to answer from, and a
# cap on the whole (the briefing's Garmin result alone was 39k characters)
_TRANSCRIPT_RESULT_CHARS = 8000
_TRANSCRIPT_MAX_CHARS = 60000


def final_transcript(messages: list[BaseMessage]) -> list[BaseMessage]:
    """The conversation as plain text, for a final call to a model without tools.

    Earlier turns stay as they are (text only); this turn - from the user's
    latest message on - becomes one message: the request, what each tool
    returned (each result cut to a few thousand characters) and the model's
    own notes. Tool calls and results can't go to a model with no tools.
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage  # noqa: PLC0415 - typing-only above

    start = next(
        (
            i
            for i in range(len(messages) - 1, -1, -1)
            if isinstance(messages[i], HumanMessage)
            and not str(messages[i].content).startswith(_GUIDANCE_PREFIX)
        ),
        0,
    )
    earlier = [
        m
        for m in messages[:start]
        if isinstance(m, HumanMessage)
        or (
            isinstance(m, AIMessage)
            and not m.tool_calls
            and extract_text_content(m.content).strip()
        )
    ]
    parts: list[str] = []
    for message in messages[start:]:
        if isinstance(message, ToolMessage):
            result = extract_text_content(message.content)[:_TRANSCRIPT_RESULT_CHARS]
            parts.append(f"[{message.name or 'tool'} returned]\n{result}")
        elif isinstance(message, HumanMessage) and not str(message.content).startswith(
            _GUIDANCE_PREFIX
        ):
            parts.append(f"[The user asked]\n{extract_text_content(message.content)}")
        elif isinstance(message, AIMessage) and (
            text := extract_text_content(message.content).strip()
        ):
            parts.append(f"[Your notes so far]\n{text}")
        elif isinstance(message, SystemMessage):
            continue
    body = "\n\n".join(parts)[:_TRANSCRIPT_MAX_CHARS]
    return [*earlier, HumanMessage(content=f"{body}\n\nWrite your final reply now.")]


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
