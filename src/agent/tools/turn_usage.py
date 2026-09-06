"""Per-turn tool-call bookkeeping.

Tools that are cheap on their own but expensive when *repeated* across rounds
(every extra round re-sends the whole conversation to the model) need to know
how often they have already run this turn so they can nudge the model toward
batching. A Sep 2026 prod audit found 866 `web_search` calls spread over 864
separate rounds - 99% of them single-query - despite the tool docstring and
system prompt both asking for batched queries. Prompt-level guidance did not
land; a counter attached to the tool *result* does, because the model reads
results far more reliably than standing instructions.

State is keyed by request id rather than held in a contextvar: the tool node
executes calls on a thread pool, and keying off the request keeps the count
correct no matter which thread a call lands on. Entries are bounded LRU-style
so a long-lived worker never accumulates them.
"""

import threading
from collections import Counter, OrderedDict

from src.agent.tool_results import get_current_request_id

# Turns tracked before the oldest is evicted. A turn's entry is tiny (a Counter
# of tool names), and only the current request is ever read, so this only needs
# to outlive concurrent in-flight turns on one worker.
_MAX_TRACKED_TURNS = 256

_counts: OrderedDict[str, Counter[str]] = OrderedDict()
_lock = threading.Lock()


def record_tool_call(tool_name: str) -> int:
    """Count one call of `tool_name` in the current turn and return the total.

    The return value INCLUDES the call being recorded, so the first call of a
    turn returns 1. Returns 0 when there is no request context (unit tests,
    evals) so callers can treat 0 as "don't nudge".
    """
    request_id = get_current_request_id()
    if not request_id:
        return 0

    with _lock:
        counter = _counts.get(request_id)
        if counter is None:
            counter = Counter()
            _counts[request_id] = counter
            while len(_counts) > _MAX_TRACKED_TURNS:
                _counts.popitem(last=False)
        _counts.move_to_end(request_id)
        counter[tool_name] += 1
        return counter[tool_name]


def get_tool_call_count(tool_name: str) -> int:
    """How many times `tool_name` has already run this turn (0 without context)."""
    request_id = get_current_request_id()
    if not request_id:
        return 0
    with _lock:
        counter = _counts.get(request_id)
        return counter[tool_name] if counter else 0


def reset_turn_usage() -> None:
    """Drop the current turn's counts (used by tests and turn teardown)."""
    request_id = get_current_request_id()
    if not request_id:
        return
    with _lock:
        _counts.pop(request_id, None)
