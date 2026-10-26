"""Per-run tools must not reuse a memoized graph (Oct 2026 deep research bug).

The compiled-graph cache is keyed by tool NAMES. Deep research wraps
research/web_search/fetch_url (and share_finding) around each run's board, with
the same names every run - so every later run's subagents got the FIRST run's
graph: its pages and findings went to the first run's board (pages_read 0,
board_entries 0, the verifier saw almost nothing) and the board digest a
subagent is shown could carry another run's (another user's) findings.
"""

from typing import Any
from unittest.mock import MagicMock, patch

from src.agent.deep_research.board import ResearchBoard, wrap_research_tools
from src.agent.graph_cache import clear_graph_cache, get_compiled_graph
from src.agent.tools import fetch_url, research, web_search


def _run_tools(board: ResearchBoard) -> list[Any]:
    return wrap_research_tools([research, web_search, fetch_url], board, 0)


def test_unmemoized_graphs_are_built_from_this_runs_tools() -> None:
    clear_graph_cache()
    first = get_compiled_graph("gemini-3.8-flash", tools=_run_tools(ResearchBoard()), memoize=False)
    second = get_compiled_graph(
        "gemini-3.8-flash", tools=_run_tools(ResearchBoard()), memoize=False
    )
    assert first is not second


def test_memoized_graphs_are_still_shared_for_module_tools() -> None:
    clear_graph_cache()
    tools = [research, web_search, fetch_url]
    assert get_compiled_graph("gemini-3.8-flash", tools=tools) is get_compiled_graph(
        "gemini-3.8-flash", tools=tools
    )


def test_deep_research_subagents_opt_out_of_memoization() -> None:
    from src.agent.deep_research import subagent

    captured: dict[str, Any] = {}

    def fake_agent(**kwargs: Any) -> Any:
        captured.update(kwargs)
        agent = MagicMock()
        agent.chat_batch.return_value = ("digest", [], {}, [])
        return agent

    with patch("src.agent.deep_research.subagent.ChatAgent", side_effect=fake_agent):
        subagent.run_subagent("brief", ResearchBoard(), 0, "req-1")

    assert captured["memoize_graph"] is False
