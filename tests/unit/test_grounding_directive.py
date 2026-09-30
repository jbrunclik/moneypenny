"""Web tool results carry the grounding directive (honesty rides on results).

Conversation sweep (Sep 2026): "your data is old" / "you're making it up" were
the most common corrections, and the product-research eval showed prices and
shops presented as verified that the pages read never showed. Prompt-level
rules were measured to be ignored in this codebase; directives attached to
tool results work - so every web result restates the rule where it is used.
"""

import json
import socket
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from src.agent.tools import fetch_url, research, web_search
from src.agent.tools.web import GROUNDING_DIRECTIVE

_RESULTS = [{"title": "T", "url": "https://shop.example/p", "snippet": "from 12 990 CZK"}]


def test_directive_names_the_specifics_and_the_fallback() -> None:
    for word in ("prices", "opening hours", "could not verify"):
        assert word in GROUNDING_DIRECTIVE


@patch("src.agent.tools.web.search_web_detailed", return_value=(_RESULTS, "brave"))
def test_single_web_search_carries_the_directive(_mock: MagicMock) -> None:
    parsed = json.loads(web_search.invoke({"query": "brompton price"}))
    assert parsed["_grounding"] == GROUNDING_DIRECTIVE


@patch("src.agent.tools.web.search_web_detailed", return_value=(_RESULTS, "brave"))
def test_batched_web_search_carries_the_directive(_mock: MagicMock) -> None:
    parsed = json.loads(web_search.invoke({"queries": ["a", "b"]}))
    assert parsed["_grounding"] == GROUNDING_DIRECTIVE


@patch("src.agent.tools.research.fetch_page_text", return_value=("Page text", None))
@patch("src.agent.tools.research.search_web", return_value=_RESULTS)
def test_research_carries_the_directive(_search: MagicMock, _fetch: MagicMock) -> None:
    parsed = json.loads(research.invoke({"question": "where to buy a brompton"}))
    assert parsed["_grounding"] == GROUNDING_DIRECTIVE


@pytest.fixture
def html_page() -> Iterator[MagicMock]:
    addrinfo = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0))]
    response = MagicMock(status_code=200, is_redirect=False)
    response.text = "<html><body><p>" + "Brompton C Line 32 990 CZK. " * 10 + "</p></body></html>"
    response.content = response.text.encode()
    response.headers = {"content-type": "text/html"}
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get.return_value = response
    with (
        patch("src.agent.tools.url_safety.socket.getaddrinfo", return_value=addrinfo),
        patch("src.agent.tools.web.httpx.Client", return_value=client),
    ):
        yield client


def test_fetched_page_carries_the_directive_outside_the_untrusted_block(
    html_page: MagicMock,
) -> None:
    result = fetch_url.invoke({"url": "https://shop.example/brompton"})
    assert GROUNDING_DIRECTIVE in result
    # Our own trusted note - after the untrusted markers, never inside them
    assert result.index(GROUNDING_DIRECTIVE) > result.index("[END UNTRUSTED WEB CONTENT]")


def test_always_on_honesty_rule_covers_unread_specifics() -> None:
    from src.agent.prompt_texts.core import BASE_SYSTEM_PROMPT

    assert "never present them as checked" in BASE_SYSTEM_PROMPT
