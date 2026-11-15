"""A page the production host is refused (403/429), or a PDF it cannot use,
is read through Exa (docs/superpowers/specs/2026-11-15-web-reading-design.md)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.agent.tools import web
from src.config import Config

_SHOP = "https://www.alza.cz/cerave-moisturising-cream-177-ml-d6159134.htm"


def _refused(status: int) -> tuple[None, str, int]:
    return None, f"HTTP {status} when fetching {_SHOP}", status


def _page(content_type: str, body: bytes = b"", text: str = "") -> MagicMock:
    page = MagicMock(status_code=200, is_redirect=False, headers={"content-type": content_type})
    page.content = body
    page.text = text
    return page


@pytest.fixture
def exa() -> Iterator[MagicMock]:
    with (
        patch.object(web, "extract_available", return_value=True),
        patch.object(web, "extract_page", return_value=("CeraVe 177 ml - 289 Kč", None)) as read,
    ):
        yield read


@pytest.mark.parametrize("status", [403, 429])
def test_a_refused_page_is_read_through_exa(exa: MagicMock, status: int) -> None:
    with patch.object(web, "_fetch_response", return_value=_refused(status)):
        text, error = web.fetch_page_text(_SHOP, 6000)
    assert (text, error) == ("CeraVe 177 ml - 289 Kč", None)
    assert exa.call_args.args == (_SHOP, 6000)
    assert exa.call_args.kwargs == {"direct_status": status}


def test_fetch_url_frames_the_exa_text_like_a_page(exa: MagicMock) -> None:
    with patch.object(web, "_fetch_response", return_value=_refused(403)):
        result = web.fetch_url.invoke({"url": _SHOP})
    assert isinstance(result, str)
    assert "289 Kč" in result
    assert "UNTRUSTED" in result.upper()
    assert web.GROUNDING_DIRECTIVE in result


@pytest.mark.parametrize(
    "failure", [(None, "HTTP 404 when fetching x", 404), (None, "timed out", None)]
)
def test_other_failures_do_not_go_to_exa(exa: MagicMock, failure: Any) -> None:
    with patch.object(web, "_fetch_response", return_value=failure):
        text, error = web.fetch_page_text(_SHOP, 6000)
    assert text is None and error == failure[1]
    exa.assert_not_called()


def test_when_exa_fails_too_the_error_says_so(exa: MagicMock) -> None:
    exa.return_value = (None, "reading service could not read it (HTTP 403)")
    with patch.object(web, "_fetch_response", return_value=_refused(403)):
        text, error = web.fetch_page_text(_SHOP, 6000)
    assert text is None
    assert error == f"HTTP 403 when fetching {_SHOP} (also unavailable through the reading service)"


def test_without_exa_the_error_stays(exa: MagicMock) -> None:
    with (
        patch.object(web, "extract_available", return_value=False),
        patch.object(web, "_fetch_response", return_value=_refused(403)),
    ):
        assert web.fetch_page_text(_SHOP, 6000) == (None, _refused(403)[1])
    exa.assert_not_called()


@pytest.mark.parametrize(
    "url", ["https://www.reddit.com/r/bikewrench/comments/1/x/", "https://old.reddit.com/r/a/"]
)
def test_reddit_never_goes_to_exa(exa: MagicMock, url: str) -> None:
    with patch.object(web, "_fetch_response", return_value=(None, "HTTP 403", 403)):
        text, _ = web.fetch_page_text(url, 6000)
    assert text is None
    exa.assert_not_called()


def test_research_sends_a_pdf_link_straight_to_exa(exa: MagicMock) -> None:
    url = "https://www.sram.com/globalassets/manual.pdf"
    with patch.object(web, "_fetch_response") as direct:
        text, _ = web.fetch_page_text(url, 6000)
    direct.assert_not_called()
    assert text == "CeraVe 177 ml - 289 Kč"


def test_research_switches_to_exa_when_the_answer_is_a_pdf(exa: MagicMock) -> None:
    pdf = _page("application/pdf", b"%PDF-1.7 ...")
    with patch.object(web, "_fetch_response", return_value=(pdf, None, None)):
        text, error = web.fetch_page_text("https://example.com/download?id=7", 6000)
    assert (text, error) == ("CeraVe 177 ml - 289 Kč", None)


def test_fetch_url_reads_a_large_pdf_through_exa(exa: MagicMock) -> None:
    big = _page("application/pdf", b"%PDF" + b"x" * (Config.FETCH_URL_MAX_FILE_SIZE_BYTES + 1))
    with patch.object(web, "_fetch_response", return_value=(big, None, None)):
        result = web.fetch_url.invoke({"url": "https://example.com/manual.pdf"})
    assert isinstance(result, str) and "289 Kč" in result


def test_fetch_url_keeps_a_small_pdf_for_the_model(exa: MagicMock) -> None:
    small = _page("application/pdf", b"%PDF-1.7 small")
    with patch.object(web, "_fetch_response", return_value=(small, None, None)):
        result = web.fetch_url.invoke({"url": "https://example.com/manual.pdf"})
    assert isinstance(result, list)
    exa.assert_not_called()


def test_a_pdf_link_exa_cannot_read_is_tried_once(exa: MagicMock) -> None:
    exa.return_value = (None, "reading service could not read it")
    pdf = _page("application/pdf", b"%PDF-1.7 ...")
    with patch.object(web, "_fetch_response", return_value=(pdf, None, None)):
        text, error = web.fetch_page_text("https://example.com/manual.pdf", 6000)
    assert text is None and error
    assert exa.call_count == 1


# ---- Final review fixes ----


def test_a_continuation_read_through_exa_starts_where_asked(
    exa: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A burst 429 on fetch_url(start=N) must not hand back the page's head."""
    monkeypatch.setattr(Config, "HTML_TEXT_MAX_LENGTH", 10)
    exa.return_value = ("a" * 10 + "b" * 10 + "c" * 5, None)
    with patch.object(web, "_fetch_response", return_value=_refused(429)):
        result = web.fetch_url.invoke({"url": _SHOP, "start": 10})
    assert "b" * 10 in result and "a" not in result.split("]")[1].split("[")[0]
    assert "call fetch_url with start=20 for more" in result
    assert exa.call_args.args == (_SHOP, 21)  # start + window + 1: knows whether more is left


def test_a_first_read_through_exa_says_when_it_was_cut(
    exa: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Config, "HTML_TEXT_MAX_LENGTH", 10)
    exa.return_value = ("x" * 11, None)
    with patch.object(web, "_fetch_response", return_value=_refused(403)):
        result = web.fetch_url.invoke({"url": _SHOP})
    assert "call fetch_url with start=10 for more" in result


@pytest.mark.parametrize(
    "url", ["http://10.0.0.5/manual.pdf", "http://localhost/x.pdf", "ftp://example.com/x.pdf"]
)
def test_a_blocked_pdf_link_never_reaches_exa(exa: MagicMock, url: str) -> None:
    text, error = web.fetch_page_text(url, 6000)
    assert text is None and error
    exa.assert_not_called()


def _client_serving(responses: dict[str, MagicMock]) -> MagicMock:
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get.side_effect = lambda url: responses[url]
    return client


def _redirect(to: str) -> MagicMock:
    return MagicMock(status_code=302, is_redirect=True, headers={"location": to})


def _forbidden(url: str) -> MagicMock:
    import httpx

    response = MagicMock(status_code=403, is_redirect=False, headers={})
    request = httpx.Request("GET", url)
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "403", request=request, response=httpx.Response(403, request=request)
    )
    return response


def test_a_redirect_ending_in_403_reads_the_original_url(exa: MagicMock) -> None:
    final = "https://www.alza.cz/final"
    client = _client_serving({_SHOP: _redirect(final), final: _forbidden(final)})
    with (
        patch.object(web.httpx, "Client", return_value=client),
        patch.object(web, "validate_public_url", return_value=None),
    ):
        text, _ = web.fetch_page_text(_SHOP, 6000)
    assert text == "CeraVe 177 ml - 289 Kč"
    assert exa.call_args.args[0] == _SHOP


def test_a_redirect_to_a_blocked_host_never_reaches_exa(exa: MagicMock) -> None:
    client = _client_serving({_SHOP: _redirect("http://169.254.169.254/latest")})
    with (
        patch.object(web.httpx, "Client", return_value=client),
        patch.object(
            web,
            "validate_public_url",
            side_effect=lambda u: "blocked address" if "169.254" in u else None,
        ),
    ):
        text, error = web.fetch_page_text(_SHOP, 6000)
    assert text is None and error is not None and "Blocked redirect" in error
    exa.assert_not_called()
