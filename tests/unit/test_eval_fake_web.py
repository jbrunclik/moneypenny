"""Canned web for eval cases (evals/fake_web.py).

The fake replaces the search and page-fetch seams, not the tools: these tests
drive the REAL research / web_search / fetch_url tools (and the freshness
gate's prefetch) through it, with no network.
"""

import json
from typing import Any

import pytest

from evals.fakes import fake_integrations

_URL = "https://www.example-bikes.cz/blog/zimni-trenink"
_PAGE = (
    "Zimní trénink na kole\n\n"
    "V zimě jezděte dvakrát týdně intervaly 4x8 minut v zóně sweet spot. "
    "Dlouhá jízda o víkendu by neměla přesáhnout tři hodiny."
)
_WEB = {
    "results": [{"url": _URL, "title": "Zimní trénink", "snippet": "Intervaly 4x8 minut"}],
    "pages": {_URL: _PAGE},
}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any real fetch or search in a canned test is a bug in the fake's patching."""

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live network call in a canned-web test")

    monkeypatch.setattr("httpx.Client.get", boom)
    monkeypatch.setattr("src.services.search_adapters.search_ddgs", boom, raising=False)


def test_research_reads_the_canned_page() -> None:
    from src.agent.tools.research import research

    with fake_integrations({}, web=_WEB) as fakes:
        out = research.invoke({"question": "zimní trénink", "queries": ["zimní trénink kolo"]})
    assert "4x8 minut" in out
    assert fakes["web"].queries == ["zimní trénink kolo"]
    assert fakes["web"].fetched == [_URL]


def test_fetch_of_an_unknown_url_is_the_tools_404_error() -> None:
    from src.agent.tools.web import fetch_url

    with fake_integrations({}, web=_WEB):
        out = fetch_url.invoke({"url": "https://other.example.org/page"})
    payload = json.loads(out) if isinstance(out, str) else {}
    assert "404" in payload.get("error", "")


def test_fetch_url_returns_a_canned_page() -> None:
    from src.agent.tools.web import fetch_url

    with fake_integrations({}, web=_WEB):
        out = fetch_url.invoke({"url": _URL})
    assert "sweet spot" in str(out)


def test_no_web_block_searches_find_nothing() -> None:
    from src.agent.tools.web import NO_RESULTS_NOTE, web_search

    with fake_integrations({}, web=None) as fakes:
        out = web_search.invoke({"query": "počasí Brno"})
    assert NO_RESULTS_NOTE in out
    assert fakes["web"].queries == ["počasí Brno"]


def test_gate_prefetch_hits_the_fake() -> None:
    from src.agent.freshness import FreshnessDecision, prefetch_messages

    decision = FreshnessDecision(lookup=True, queries=["zimní trénink kolo"])
    with fake_integrations({}, web=_WEB) as fakes:
        messages = prefetch_messages(decision, "Jak trénovat v zimě?")
    assert fakes["web"].queries == ["zimní trénink kolo"]
    assert "4x8 minut" in str(messages[-1].content)


def test_browser_is_unavailable_on_canned_web() -> None:
    from src.agent.tools.browser import browser

    with fake_integrations({}, web=_WEB):
        out = browser.invoke({"action": "navigate", "url": _URL})
    assert "not available" in json.loads(out)["error"]


def test_live_web_installs_no_fake() -> None:
    from src.agent.tools import web

    original = web._fetch_response
    with fake_integrations({}, web="live") as fakes:
        assert web._fetch_response is original
        assert "web" not in fakes


@pytest.mark.parametrize(
    "asked",
    [
        _URL + "/",
        _URL + "#zone2",
        _URL.replace("https://", "http://"),
        _URL.replace("www.example-bikes.cz", "WWW.Example-Bikes.cz"),
    ],
)
def test_a_canned_page_matches_url_variants(asked: str) -> None:
    from src.agent.tools.web import fetch_url

    with fake_integrations({}, web=_WEB):
        out = fetch_url.invoke({"url": asked})
    assert "sweet spot" in str(out)


def test_canned_web_calls_are_summarized() -> None:
    from evals.fake_web import FakeWeb

    fake = FakeWeb(_WEB)
    fake.search_web_detailed("a", 3)
    fake.fetch_response(_URL)
    fake.fetch_response("https://elsewhere.example.org/x")
    assert fake.summary() == {
        "searches": 1,
        "fetched": [_URL, "https://elsewhere.example.org/x"],
        "missing": ["https://elsewhere.example.org/x"],
    }
