"""Per-run override of AGENT_MAX_TOOL_ROUNDS (contextvar: per thread/turn).

Deep-research subagents get a smaller budget than a chat turn; the graph reads
the cap through tool_round_cap(), so the override never leaks into other turns.
"""

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

from src.config import Config

_override: contextvars.ContextVar[int | None] = contextvars.ContextVar("round_cap", default=None)


def tool_round_cap() -> int:
    override = _override.get()
    return Config.AGENT_MAX_TOOL_ROUNDS if override is None else override


@contextmanager
def round_cap_override(rounds: int) -> Iterator[None]:
    token = _override.set(rounds)
    try:
        yield
    finally:
        _override.reset(token)
