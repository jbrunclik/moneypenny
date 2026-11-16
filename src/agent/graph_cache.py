"""Compiled-graph memoization.

create_chat_graph + compile_graph ran in ChatAgent.__init__ on every request,
rebuilding + recompiling a graph that is a pure function of its build
signature. The compiled graph is stateless (state is passed per invoke; the
request id rides a contextvar, not the graph), so it is safe to compile once
per signature and share across requests and threads.
"""

import threading
from collections import OrderedDict
from typing import Any

from src.agent.graph import compile_graph, create_chat_graph
from src.agent.tools import get_available_tools
from src.config import Config

# per-worker: a memo of compiled graphs, rebuilt on a miss
_compiled_graph_cache: OrderedDict[tuple[Any, ...], Any] = OrderedDict()
_compiled_graph_lock = threading.Lock()


def _graph_signature(
    model_name: str,
    *,
    with_tools: bool,
    include_thoughts: bool,
    tools: list[Any],
    is_autonomous: bool,
    thinking_level: str | None,
) -> tuple[Any, ...]:
    """Everything the compiled graph depends on. Tool names are sorted so the
    key is order-independent (the tool set, not its ordering, matters)."""
    tool_sig = tuple(sorted(t.name for t in tools)) if tools else ()
    return (
        model_name,
        with_tools,
        include_thoughts,
        tool_sig,
        is_autonomous,
        thinking_level,
    )


def clear_graph_cache() -> None:
    """Drop all memoized compiled graphs (used by tests for isolation)."""
    with _compiled_graph_lock:
        _compiled_graph_cache.clear()


def _store(key: tuple[Any, ...], compiled: Any) -> None:
    """Memoize a compiled graph, evicting the LRU tail."""
    with _compiled_graph_lock:
        _compiled_graph_cache[key] = compiled
        _compiled_graph_cache.move_to_end(key)
        max_size = Config.AGENT_GRAPH_CACHE_SIZE
        while max_size > 0 and len(_compiled_graph_cache) > max_size:
            _compiled_graph_cache.popitem(last=False)  # evict least-recently-used


def get_compiled_graph(
    model_name: str,
    with_tools: bool = True,
    include_thoughts: bool = False,
    tools: list[Any] | None = None,
    is_autonomous: bool = False,
    memoize: bool = True,
    thinking_level: str | None = None,
) -> Any:
    """Return a compiled chat graph for this signature, building it once.

    `memoize=False` for tools that are per-run closures (deep research wraps
    its tools around each run's board, with the same names every run): the
    signature knows only tool names, so a memoized graph would run an earlier
    run's tools.

    Bounded LRU (Config.AGENT_GRAPH_CACHE_SIZE).
    """
    active_tools = tools if tools is not None else get_available_tools()
    build_args: dict[str, Any] = {
        "with_tools": with_tools,
        "include_thoughts": include_thoughts,
        "tools": active_tools,
        "is_autonomous": is_autonomous,
        "thinking_level": thinking_level,
    }
    if not memoize:
        return compile_graph(create_chat_graph(model_name, **build_args))
    key = _graph_signature(model_name, **build_args)

    with _compiled_graph_lock:
        cached = _compiled_graph_cache.get(key)
        if cached is not None:
            _compiled_graph_cache.move_to_end(key)  # mark most-recently-used
            return cached

    # Build outside the lock - compilation is the slow part we don't want to
    # serialize. A rare concurrent double-build is harmless (both are valid);
    # the second store just overwrites with an equivalent graph.
    compiled = compile_graph(create_chat_graph(model_name, **build_args))
    _store(key, compiled)
    return compiled
