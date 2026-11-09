"""Turn budgets' loop detector (Hermes `agent/tool_guardrails.py`, adapted).

A call is identified by its tool name and canonical arguments. Within one
turn: a call that failed TURN_LOOP_BLOCK_AFTER times is answered with an
error instead of running again, rounds alternating between the same two
calls (A-B-A-B) get one warning, a successful write resets the counts (the
world changed, so a retry may now work), and a large byte-identical repeat
result becomes a back-reference instead of being re-read.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from src.agent.permissions import WRITE_LEVEL_TOOLS
from src.config import Config
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from langchain_core.messages import ToolCall

    from src.agent.graph_state import AgentState

logger = get_logger(__name__)

BLOCKED_MESSAGE = (
    "This exact call already failed twice this turn - change the approach or answer "
    "with what you have."
)
BACK_REFERENCE = "Same result as the earlier identical call (unchanged)."
AB_WARNING = (
    "You are alternating between the same two calls without new information. Change the "
    "approach, or answer with what you have."
)
# Tools whose success changes the world (so a failed read may now succeed)
_WRITES = frozenset({*WRITE_LEVEL_TOOLS, "manage_memory"})


def call_signature(name: str, args: Mapping[str, object]) -> str:
    """One call's identity: its tool and canonical arguments."""
    canonical = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(f"{name}\0{canonical}".encode()).hexdigest()  # noqa: S324 - identity, not security


def _signature(call: ToolCall) -> str:
    return call_signature(call["name"], call.get("args") or {})


def blocked_calls(failed_calls: Mapping[str, int], calls: Sequence[ToolCall]) -> set[str]:
    """Ids of the calls that already failed TURN_LOOP_BLOCK_AFTER times."""
    limit = Config.TURN_LOOP_BLOCK_AFTER
    return {c["id"] or "" for c in calls if failed_calls.get(_signature(c), 0) >= limit}


def blocked_message(call: ToolCall) -> ToolMessage:
    """The error a blocked call gets instead of running (it counts as a failure)."""
    logger.info("Tool loop blocked", extra={"tool": call["name"]})
    content = json.dumps({"error": BLOCKED_MESSAGE, "retriable": False})
    return ToolMessage(content=content, tool_call_id=call["id"] or "", name=call["name"])


def _latest_round(messages: Sequence[BaseMessage]) -> tuple[list[ToolCall], list[ToolMessage]]:
    """The latest round's calls and their results."""
    results: list[ToolMessage] = []
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            results.append(message)
        elif isinstance(message, AIMessage):
            return list(message.tool_calls), list(reversed(results))
        else:
            continue
    return [], []


def _failed(message: ToolMessage) -> bool:
    from src.agent.tool_round_check import tool_message_error  # noqa: PLC0415 - cycle: tool_round_check imports this

    return tool_message_error(message) is not None


def is_ab_cycle(recent: Sequence[str]) -> bool:
    """The last four rounds alternate between two different calls."""
    if len(recent) < 4:
        return False
    a, b, c, d = recent[-4:]
    return a == c and b == d and a != b


def loop_state(state: AgentState) -> tuple[dict[str, object], str | None]:
    """After a round: updated failure counts and recent rounds, and the
    one-off A-B-A-B warning when it is due."""
    calls, results = _latest_round(state["messages"])
    by_id = {c["id"]: c for c in calls}
    failed = dict(state.get("failed_calls", {}))
    for result in results:
        call = by_id.get(result.tool_call_id)
        if call is None:
            continue
        if _failed(result):
            sig = _signature(call)
            failed[sig] = failed.get(sig, 0) + 1
        elif call["name"] in _WRITES:
            failed = {}
    round_sig = "|".join(sorted(_signature(c) for c in calls))
    recent = [*state.get("recent_rounds", []), round_sig][-4:]
    update: dict[str, object] = {"failed_calls": failed, "recent_rounds": recent}
    if is_ab_cycle(recent) and not state.get("ab_warned"):
        update["ab_warned"] = True
        logger.info("Tool loop A-B-A-B warning")
        return update, AB_WARNING
    return update, None


def dedupe_results(
    results: Sequence[ToolMessage], calls: Sequence[ToolCall], seen: Mapping[str, str]
) -> tuple[list[ToolMessage], dict[str, str]]:
    """Results with large byte-identical repeats replaced by a back-reference,
    and the updated signature -> content-hash map."""
    by_id = {c["id"]: c for c in calls}
    seen_now = dict(seen)
    out: list[ToolMessage] = []
    for result in results:
        call = by_id.get(result.tool_call_id)
        content = result.content if isinstance(result.content, str) else None
        if call is None or content is None or len(content) < Config.TURN_DUPLICATE_RESULT_MIN_CHARS:
            out.append(result)
            continue
        sig = _signature(call)
        digest = hashlib.sha1(content.encode()).hexdigest()  # noqa: S324 - identity, not security
        if seen_now.get(sig) == digest:
            out.append(result.model_copy(update={"content": BACK_REFERENCE}))
        else:
            seen_now[sig] = digest
            out.append(result)
    return out, seen_now
