"""fetch_url reads past its cut and lists the page's links
(docs/superpowers/specs/2026-11-15-web-reading-design.md)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agent.tools import web
from src.agent.tools.web_content import extract_links
from src.config import Config

_URL = "https://example.com/guide/"


def _html_page(body: str) -> MagicMock:
    page = MagicMock(status_code=200, is_redirect=False, headers={"content-type": "text/html"})
    page.text = f"<html><body><article>{body}</article></body></html>"
    return page


def _text_page(text: str) -> MagicMock:
    page = MagicMock(status_code=200, is_redirect=False, headers={"content-type": "text/plain"})
    page.text = text
    page.content = text.encode()
    return page


def _fetch(page: MagicMock, start: int = 0) -> str:
    with patch.object(web, "_fetch_response", return_value=(page, None, None)):
        result = web.fetch_url.invoke({"url": _URL, "start": start})
    assert isinstance(result, str)
    return result


@pytest.fixture
def small_limit(monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(Config, "HTML_TEXT_MAX_LENGTH", 100)
    return 100


def test_a_long_page_says_where_to_continue(small_limit: int) -> None:
    text = "a" * 250
    result = _fetch(_text_page(text))
    assert "a" * 100 in result and "a" * 101 not in result
    assert "[Truncated at 100 of 250 characters - call fetch_url with start=100 for more]" in result


def test_start_continues_from_there(small_limit: int) -> None:
    text = "a" * 100 + "b" * 100 + "c" * 50
    result = _fetch(_text_page(text), start=100)
    assert "b" * 100 in result and "a" not in result.split("[")[0]
    assert "call fetch_url with start=200 for more" in result


def test_the_last_window_has_no_continue_note(small_limit: int) -> None:
    result = _fetch(_text_page("a" * 150), start=100)
    assert "a" * 50 in result
    assert "start=" not in result


def test_start_past_the_end_says_so(small_limit: int) -> None:
    result = _fetch(_text_page("a" * 150), start=400)
    assert "[Nothing after character 400 - the page has 150 characters]" in result


def test_a_short_page_is_whole(small_limit: int) -> None:
    result = _fetch(_text_page("short page"))
    assert "short page" in result and "Truncated" not in result


def test_html_pages_continue_too(small_limit: int) -> None:
    body = "<p>" + "word " * 60 + "</p>"
    first = _fetch(_html_page(body))
    assert "call fetch_url with start=100 for more" in first


def test_the_links_follow_the_text() -> None:
    body = (
        "<p>" + "Plenty of page text. " * 10 + "</p>"
        '<a href="/manuals/rs-pump.pdf">Pump manual</a>'
        '<a href="https://other.example/x">Other site</a>'
    )
    result = _fetch(_html_page(body))
    assert "Links:" in result
    assert "- Pump manual: https://example.com/manuals/rs-pump.pdf" in result
    assert "- Other site: https://other.example/x" in result
    assert result.index("Links:") < result.index(web.GROUNDING_DIRECTIVE)


def test_a_continuation_does_not_repeat_the_links(small_limit: int) -> None:
    body = "<p>" + "word " * 60 + '</p><a href="/a">A link</a>'
    assert "Links:" not in _fetch(_html_page(body), start=100)


def test_link_extraction() -> None:
    html = (
        '<a href="/a">First</a><a href="/a">First again</a>'
        '<a href="#top">Top</a><a href="javascript:void(0)">JS</a>'
        '<a href="mailto:x@example.com">Mail</a><a href="b?q=1"> Second\n link </a>'
        '<a href="/img"><img src="x.png"></a>'
    )
    assert extract_links(html, _URL, 40) == [
        ("First", "https://example.com/a"),
        ("Second link", "https://example.com/guide/b?q=1"),
        ("", "https://example.com/img"),
    ]


def test_links_are_capped() -> None:
    html = "".join(f'<a href="/p{i}">Page {i}</a>' for i in range(60))
    assert (
        len(extract_links(html, _URL, Config.FETCH_URL_MAX_LINKS))
        == 40
        == Config.FETCH_URL_MAX_LINKS
    )


def test_start_past_the_end_has_no_empty_wrapper(small_limit: int) -> None:
    result = _fetch(_text_page("a" * 150), start=400)
    assert "UNTRUSTED" not in result.upper()
    assert "[Nothing after character 400 - the page has 150 characters]" in result


def test_links_resolve_against_the_final_url_after_redirects() -> None:
    import httpx

    page = _html_page("<p>" + "Plenty of page text. " * 10 + '</p><a href="manual.pdf">Manual</a>')
    page.url = httpx.URL("https://example.com/docs/v2/")  # where the redirects ended
    result = _fetch(page)
    assert "- Manual: https://example.com/docs/v2/manual.pdf" in result


def test_a_negative_start_reads_from_the_top(small_limit: int) -> None:
    page = _text_page("a" * 100 + "b" * 50)
    assert _fetch(page, start=-30) == _fetch(page)
