"""Automatic source chips from the pages a turn actually read.

Replaces the cite_sources tool: the model sent it without answer text in 79%
of tool-using turns (Sep 2026: 687 of 869), costing a full extra model round
each time (~49M input tokens/month), and forgot it in others.
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, ToolMessage

from src.agent.content import extract_read_sources


def _turn(*calls: tuple[str, dict, object]) -> list:
    messages: list = []
    for i, (name, args, result) in enumerate(calls):
        messages.append(
            AIMessage(content="", tool_calls=[{"id": f"c{i}", "name": name, "args": args}])
        )
        content = result if isinstance(result, str | list) else json.dumps(result)
        messages.append(ToolMessage(content=content, tool_call_id=f"c{i}", name=name))
    messages.append(AIMessage(content="answer"))
    return messages


def test_research_pages_read_are_sources_not_failed_or_unfetched() -> None:
    sources = extract_read_sources(
        _turn(
            (
                "research",
                {"question": "q"},
                {
                    "sources": [
                        {
                            "title": "Apple specs",
                            "url": "https://apple.com/specs",
                            "content": "...",
                        },
                        {"title": "Broken", "url": "https://broken", "error": "HTTP 403"},
                    ],
                    "unfetched": [{"title": "Later", "url": "https://later"}],
                },
            )
        )
    )
    assert sources == [{"title": "Apple specs", "url": "https://apple.com/specs"}]


def test_fetched_url_is_a_source_failed_fetch_is_not() -> None:
    sources = extract_read_sources(
        _turn(
            (
                "fetch_url",
                {"url": "https://www.example.com/guide/start"},
                "UNTRUSTED ... page text",
            ),
            ("fetch_url", {"url": "https://down.example"}, {"error": "HTTP 500"}),
        )
    )
    assert sources == [
        {"title": "example.com/guide/start", "url": "https://www.example.com/guide/start"}
    ]


def test_fetched_pdf_counts() -> None:
    sources = extract_read_sources(
        _turn(("fetch_url", {"url": "https://x.org/report.pdf"}, [{"type": "media"}]))
    )
    assert sources[0]["url"] == "https://x.org/report.pdf"


def test_browser_pages_and_delegate_sources() -> None:
    sources = extract_read_sources(
        _turn(
            (
                "browser",
                {"action": "navigate", "url": "https://shop"},
                {"success": True, "title": "Shop", "url": "https://shop/home"},
            ),
            ("browser", {"action": "click"}, {"success": False, "error": "not found"}),
            (
                "delegate_task",
                {"task": "t"},
                {"result": "r", "sources": [{"title": "D", "url": "https://d"}]},
            ),
        )
    )
    assert sources == [
        {"title": "Shop", "url": "https://shop/home"},
        {"title": "D", "url": "https://d"},
    ]


def test_search_results_only_when_nothing_was_read() -> None:
    search = {
        "searches": [
            {
                "query": "a",
                "results": [{"title": f"A{i}", "url": f"https://a{i}"} for i in range(4)],
            },
            {
                "query": "b",
                "results": [{"title": f"B{i}", "url": f"https://b{i}"} for i in range(4)],
            },
        ]
    }
    snippet_only = extract_read_sources(_turn(("web_search", {"queries": ["a", "b"]}, search)))
    # Rank-interleaved across queries, capped at 5
    assert [s["url"] for s in snippet_only] == [
        "https://a0",
        "https://b0",
        "https://a1",
        "https://b1",
        "https://a2",
    ]

    with_read_page = extract_read_sources(
        _turn(
            ("web_search", {"queries": ["a", "b"]}, search),
            ("fetch_url", {"url": "https://a0"}, "page text"),
        )
    )
    assert [s["url"] for s in with_read_page] == ["https://a0"]


def test_single_search_shape_and_dedupe() -> None:
    sources = extract_read_sources(
        _turn(
            (
                "web_search",
                {"query": "q"},
                {"query": "q", "results": [{"title": "T", "url": "https://t"}]},
            ),
            (
                "web_search",
                {"query": "q2"},
                {"query": "q2", "results": [{"title": "T", "url": "https://t"}]},
            ),
        )
    )
    assert sources == [{"title": "T", "url": "https://t"}]


def test_no_web_tools_no_sources() -> None:
    assert extract_read_sources(_turn(("kv_store", {}, {"ok": True}))) == []
    assert extract_read_sources([]) == []
