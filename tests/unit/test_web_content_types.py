"""JSON and XML/RSS/Atom feeds are read as text instead of refused
(docs/superpowers/specs/2026-11-15-web-reading-design.md)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agent.tools import web
from src.agent.tools.web_content import content_type_category
from src.config import Config


def _page(content_type: str, text: str) -> MagicMock:
    page = MagicMock(status_code=200, is_redirect=False, headers={"content-type": content_type})
    page.text = text
    page.content = text.encode()
    return page


@pytest.mark.parametrize(
    "content_type",
    [
        "application/json",
        "application/json; charset=utf-8",
        "application/ld+json",
        "application/xml",
        "text/xml",
        "application/rss+xml",
        "application/atom+xml",
    ],
)
def test_data_types_are_readable(content_type: str) -> None:
    assert content_type_category(content_type) == "data"


def test_json_is_pretty_printed_with_its_letters_kept() -> None:
    page = _page("application/json", '{"město":"Praha","items":[1,2]}')
    with patch.object(web, "_fetch_response", return_value=(page, None, None)):
        result = web.fetch_url.invoke({"url": "https://api.example/data.json"})
    assert '"město": "Praha"' in result
    assert '  "items": [' in result


def test_invalid_json_is_shown_as_it_came() -> None:
    page = _page("application/json", "{not json")
    with patch.object(web, "_fetch_response", return_value=(page, None, None)):
        result = web.fetch_url.invoke({"url": "https://api.example/broken"})
    assert "{not json" in result


def test_a_feed_reads_as_text_for_research() -> None:
    feed = "<rss><channel><item><title>Výluka linky 22</title></item></channel></rss>"
    with patch.object(
        web, "_fetch_response", return_value=(_page("application/rss+xml", feed), None, None)
    ):
        text, error = web.fetch_page_text("https://dpp.example/feed", 6000)
    assert error is None and text is not None and "Výluka linky 22" in text


def test_data_follows_the_text_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "HTML_TEXT_MAX_LENGTH", 50)
    page = _page("application/json", '{"a": "' + "x" * 200 + '"}')
    with patch.object(web, "_fetch_response", return_value=(page, None, None)):
        result = web.fetch_url.invoke({"url": "https://api.example/big.json"})
    assert "call fetch_url with start=50 for more" in result
