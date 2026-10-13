"""Unit tests for the turn's numbered page list (src/agent/source_pages.py)."""

import json

from langchain_core.messages import AIMessage, ToolMessage

from src.agent.content import extract_read_sources
from src.agent.source_pages import SourcePage, turn_pages, uncited_web_text


def _call(name: str, call_id: str, args: dict[str, object] | None = None) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": call_id}])


def _result(name: str, call_id: str, content: object) -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call_id, name=name)


def _research(*pages: tuple[str, str, str | None]) -> str:
    sources = []
    for title, url, text in pages:
        source: dict[str, object] = {"title": title, "url": url}
        if text is not None:
            source["content"] = text
        sources.append(source)
    return json.dumps({"sources": sources})


def test_research_pages_carry_their_text_in_chip_order() -> None:
    messages = [
        _call("research", "r1"),
        _result(
            "research",
            "r1",
            _research(
                ("SPZ Služby", "https://spzsluzby.cz", "Vyřízení do 24 hodin."),
                ("Failed", "https://failed.cz", None),  # not fetched: not read
                ("Pomocnice", "https://pomocnice.cz/x", "Cena 1 590 Kč."),
            ),
        ),
    ]

    assert turn_pages(messages) == [
        SourcePage("SPZ Služby", "https://spzsluzby.cz", "Vyřízení do 24 hodin."),
        SourcePage("Pomocnice", "https://pomocnice.cz/x", "Cena 1 590 Kč."),
    ]
    assert extract_read_sources(messages) == [
        {"title": "SPZ Služby", "url": "https://spzsluzby.cz"},
        {"title": "Pomocnice", "url": "https://pomocnice.cz/x"},
    ]


def test_fetch_url_page_text_is_the_tool_output() -> None:
    messages = [
        _call("fetch_url", "f1", {"url": "https://www.example.cz/cenik"}),
        _result("fetch_url", "f1", "Ceník: přepis 1 590 Kč"),
    ]

    assert turn_pages(messages) == [
        SourcePage("example.cz/cenik", "https://www.example.cz/cenik", "Ceník: přepis 1 590 Kč")
    ]


def test_search_snippets_are_pages_only_when_nothing_was_read() -> None:
    search = json.dumps(
        {"results": [{"title": "A", "url": "https://a.cz", "snippet": "A sells it for 100 Kč"}]}
    )
    only_search = [_call("web_search", "s1"), _result("web_search", "s1", search)]

    assert turn_pages(only_search) == [SourcePage("A", "https://a.cz", "A sells it for 100 Kč")]
    assert uncited_web_text(only_search) == ""

    with_fetch = [
        *only_search,
        _call("fetch_url", "f1", {"url": "https://b.cz"}),
        _result("fetch_url", "f1", "B page"),
    ]
    assert [p.url for p in turn_pages(with_fetch)] == ["https://b.cz"]
    # The snippet still informs the verifier, it just can't be cited
    assert "A sells it for 100 Kč" in uncited_web_text(with_fetch)


def test_unparsed_web_tool_text_is_uncited() -> None:
    messages = [_result("research", "r1", "Kolo stojí 32 990 Kč u Bike Prague.")]

    assert turn_pages(messages) == []
    assert uncited_web_text(messages) == "Kolo stojí 32 990 Kč u Bike Prague."


def _research_with_snippets() -> str:
    """Oct 2026 Gyeon turn: one page read, one fetch 429'd, one candidate unfetched."""
    return json.dumps(
        {
            "sources": [
                {"title": "Rim EVO", "url": "https://shop.cz/rim", "content": "Q2 Rim EVO 30 ml"},
                {
                    "title": "Gyeon guide",
                    "url": "https://guide.com/gyeon",
                    "snippet": "Every Gyeon product: Q2M WetCoat, Q2 CanCoat EVO",
                    "error": "HTTP 429",
                },
            ],
            "unfetched": [
                {"title": "Bike", "url": "https://bike.org", "snippet": "WetCoat on a bike frame"}
            ],
        }
    )


def test_research_snippets_inform_the_verifier_uncited() -> None:
    # The model reads research's snippets too; the verifier used to see only
    # the fetched pages and flagged products named in the snippets
    messages = [_call("research", "r1"), _result("research", "r1", _research_with_snippets())]

    assert [p.url for p in turn_pages(messages)] == ["https://shop.cz/rim"]
    uncited = uncited_web_text(messages)
    assert "Every Gyeon product: Q2M WetCoat, Q2 CanCoat EVO" in uncited
    assert "WetCoat on a bike frame" in uncited


def test_research_snippets_are_pages_when_no_fetch_succeeded() -> None:
    data = json.loads(_research_with_snippets())
    data["sources"] = data["sources"][1:]
    messages = [_call("research", "r1"), _result("research", "r1", json.dumps(data))]

    assert turn_pages(messages) == [
        SourcePage(
            "Gyeon guide",
            "https://guide.com/gyeon",
            "Every Gyeon product: Q2M WetCoat, Q2 CanCoat EVO",
        ),
        SourcePage("Bike", "https://bike.org", "WetCoat on a bike frame"),
    ]
