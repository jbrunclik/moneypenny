"""Second single-query web_search in a turn runs as research (search + read).

Sep 30 2026 audit: the escalating _efficiency nudges did not move traffic -
63% of search turns still ran 2+ separate search rounds (67% before) and
rounds per tool-using turn stayed at 2.68. Instead of asking, the follow-up
search now returns the top pages already read, which removes the
search -> fetch round and gives the model enough to stop searching.
"""

import json
import uuid
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.agent.content import extract_read_sources
from src.agent.tool_results import set_current_request_id
from src.agent.tools import web_search
from src.config import Config

_RESULTS = [{"title": "T", "url": "https://a.example/1", "snippet": "s"}]
# research searches separately: a distinct URL proves which path produced a source
_READ = [{"title": "R", "url": "https://read.example/page", "snippet": "s"}]


@pytest.fixture
def turn() -> Iterator[None]:
    set_current_request_id(f"req-{uuid.uuid4()}")
    yield
    set_current_request_id(None)


@pytest.fixture
def providers() -> Iterator[dict[str, MagicMock]]:
    with (
        patch("src.agent.tools.web.search_web_detailed", return_value=(_RESULTS, "brave")) as ws,
        patch("src.agent.tools.research.search_web", return_value=_READ) as rs,
        patch("src.agent.tools.research.fetch_page_text", return_value=("Page text", None)) as rf,
    ):
        yield {"web": ws, "research_search": rs, "research_fetch": rf}


def test_first_search_is_a_plain_search(turn: None, providers: dict[str, MagicMock]) -> None:
    parsed = json.loads(web_search.invoke({"query": "brompton dealers prague"}))
    assert "results" in parsed
    assert "_escalated" not in parsed
    providers["research_fetch"].assert_not_called()


def test_second_single_search_runs_as_research(turn: None, providers: dict[str, MagicMock]) -> None:
    web_search.invoke({"query": "brompton dealers prague"})
    parsed = json.loads(web_search.invoke({"query": "brompton c line price czk"}))

    assert "_escalated" in parsed
    assert parsed["sources"][0]["content"]
    assert "UNTRUSTED WEB CONTENT" in parsed["sources"][0]["content"]
    assert "_grounding" in parsed
    assert "_efficiency" not in parsed
    fetched = providers["research_fetch"].call_count
    assert 1 <= fetched <= Config.WEB_SEARCH_ESCALATE_MAX_SOURCES


def test_batched_calls_are_never_escalated(turn: None, providers: dict[str, MagicMock]) -> None:
    web_search.invoke({"query": "first"})
    parsed = json.loads(web_search.invoke({"queries": ["a", "b"]}))
    assert "searches" in parsed
    assert "_escalated" not in parsed
    providers["research_fetch"].assert_not_called()


def test_no_escalation_without_a_turn(providers: dict[str, MagicMock]) -> None:
    set_current_request_id(None)
    web_search.invoke({"query": "one"})
    parsed = json.loads(web_search.invoke({"query": "two"}))
    assert "_escalated" not in parsed


def test_escalated_pages_become_source_chips(turn: None, providers: dict[str, MagicMock]) -> None:
    web_search.invoke({"query": "first"})
    result = web_search.invoke({"query": "second"})
    messages = [
        AIMessage(
            content="", tool_calls=[{"name": "web_search", "args": {"query": "second"}, "id": "c2"}]
        ),
        ToolMessage(content=result, tool_call_id="c2", name="web_search"),
    ]
    assert {s["url"] for s in extract_read_sources(messages)} == {"https://read.example/page"}
