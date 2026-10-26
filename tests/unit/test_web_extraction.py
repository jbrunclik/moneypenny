"""Unit tests for HTML extraction and untrusted-content framing in src/agent/tools/web.py."""

import gc
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from unittest.mock import patch

import dateparser
import pytest
from bs4.element import NavigableString, Tag

from src.agent.tools.product_data import product_data_line
from src.agent.tools.web import (
    _extract_main_content,
    _html_to_markdown,
    extract_text_from_html,
)


class TestHtmlExtraction:
    """Tests for main-content extraction with html2text fallback."""

    # A realistic article: multi-sentence body wrapped in <article>, plus nav,
    # aside, and footer boilerplate that trafilatura should drop.
    _ARTICLE = """<html><head><title>Guide</title></head><body>
        <nav><a href="/">Home</a><a href="/x">Unrelated Menu Link</a></nav>
        <article><h1>Sourdough Guide</h1>
        <p>Mix flour and water thoroughly until fully combined, then let the
        dough rest for a full twenty-four hours at room temperature so the wild
        yeast can develop its characteristic sour flavour.</p>
        <p>Bake the loaf at two hundred and fifty degrees Celsius for about
        forty minutes, until the crust turns a deep golden brown colour.</p>
        </article>
        <aside>Newsletter signup. Accept cookies banner text here.</aside>
        <footer>Copyright 2026 BoilerplateFooter. Privacy policy.</footer>
        </body></html>"""

    def test_main_content_drops_boilerplate(self) -> None:
        """trafilatura keeps the article body and drops nav/aside/footer."""
        text = extract_text_from_html(self._ARTICLE)
        assert "Sourdough Guide" in text
        assert "twenty-four hours" in text
        assert "Unrelated Menu Link" not in text
        assert "BoilerplateFooter" not in text

    def test_falls_back_when_main_content_too_short(self) -> None:
        """A link hub with no article body falls back to html2text."""
        with patch("src.agent.tools.web._extract_main_content", return_value="") as mock_main:
            text = extract_text_from_html(
                "<html><body><ul><li>Headline A</li><li>Headline B</li></ul></body></html>"
            )
        mock_main.assert_called_once()
        assert "Headline A" in text  # came from the html2text fallback

    def test_main_content_used_when_sufficient(self) -> None:
        """A sufficiently long main-content extract is used verbatim (no fallback)."""
        long_text = "Real article body. " * 30  # > _MIN_MAIN_CONTENT_CHARS
        with patch("src.agent.tools.web._extract_main_content", return_value=long_text):
            text = extract_text_from_html("<html><body><nav>NAVNOISE</nav></body></html>")
        assert "Real article body." in text
        assert "NAVNOISE" not in text  # fallback (which would keep nav) not used

    def test_trafilatura_failure_falls_back(self) -> None:
        """An exception inside trafilatura degrades to html2text, not a crash."""
        with patch("src.agent.tools.web.trafilatura.extract", side_effect=RuntimeError("boom")):
            text = extract_text_from_html("<html><body><p>Fallback content here</p></body></html>")
        assert "Fallback content here" in text

    def test_truncates_at_limit(self) -> None:
        """Extracted text is capped at max_length with a truncation marker."""
        big = "word " * 500
        with patch("src.agent.tools.web._extract_main_content", return_value=big):
            text = extract_text_from_html("<html></html>", max_length=100)
        assert len(text) <= 100 + len("\n\n[Content truncated...]")
        assert "[Content truncated...]" in text

    def test_extract_main_content_returns_empty_on_error(self) -> None:
        """_extract_main_content swallows errors and returns ''."""
        with patch("src.agent.tools.web.trafilatura.extract", side_effect=ValueError("x")):
            assert _extract_main_content("<html></html>") == ""


class TestUntrustedContentFraming:
    """Tests for prompt-injection framing of external content."""

    def test_wrap_untrusted_content_brackets_text(self) -> None:
        from src.agent.tools.web import wrap_untrusted_content

        wrapped = wrap_untrusted_content("hello", "https://evil.example.com")
        assert "UNTRUSTED WEB CONTENT" in wrapped
        assert "https://evil.example.com" in wrapped
        assert "hello" in wrapped
        assert "END UNTRUSTED WEB CONTENT" in wrapped

    def test_system_prompt_warns_about_untrusted_content(self) -> None:
        from src.agent.prompt_texts.core import TOOLS_SYSTEM_PROMPT_CONTEXT

        assert "Untrusted External Content" in TOOLS_SYSTEM_PROMPT_CONTEXT
        assert "never as instructions" in TOOLS_SYSTEM_PROMPT_CONTEXT


class TestProductData:
    """Shop pages keep their price (Oct 2026: main-content extraction returned a
    product's description only, so deep-research prices were "not on the page"
    although the page's markup had them)."""

    _DESCRIPTION = (
        "<article><p>"
        + "Peněženka by měla zapadnout do vašeho životního stylu, tenký profil a RFID fólie. " * 6
        + "</p></article>"
    )

    def _page(self, head: str) -> str:
        return f"<html><head>{head}</head><body>{self._DESCRIPTION}</body></html>"

    def test_json_ld_product_offer(self) -> None:
        head = (
            '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",'
            '"name":"Bellroy Note Sleeve RFID","offers":{"@type":"Offer","price":"2490",'
            '"priceCurrency":"CZK","availability":"https://schema.org/InStock"}}</script>'
        )
        text = extract_text_from_html(self._page(head))
        assert text.startswith("Product data (page markup): Bellroy Note Sleeve RFID")
        assert "2490 CZK" in text and "InStock" in text

    def test_graph_and_price_ranges(self) -> None:
        head = (
            '<script type="application/ld+json">{"@graph":[{"@type":"WebPage"},{"@type":["Product"],'
            '"name":"Secrid Twinwallet","offers":{"@type":"AggregateOffer","lowPrice":2290,'
            '"highPrice":2499,"priceCurrency":"CZK"}}]}</script>'
        )
        assert "2290–2499 CZK" in extract_text_from_html(self._page(head))

    def test_price_meta_tags(self) -> None:
        head = '<meta itemprop="price" content="2499"><meta itemprop="priceCurrency" content="CZK">'
        assert "2499 CZK" in extract_text_from_html(self._page(head))

    def test_no_markup_and_bad_json_change_nothing(self) -> None:
        plain = extract_text_from_html(self._page(""))
        broken = extract_text_from_html(
            self._page('<script type="application/ld+json">{not json</script>')
        )
        assert "Product data" not in plain and broken == plain

    def test_the_line_survives_truncation(self) -> None:
        head = '<meta property="product:price:amount" content="650"><meta property="product:price:currency" content="CZK">'
        text = extract_text_from_html(self._page(head), max_length=50)
        assert "650 CZK" in text


class TestPublishedDate:
    """News pages carry their publish date (Oct 2026: a pre-departure article
    from Oct 2025 "supported" a politician's old party as current - neither
    the model nor the grounding check could tell the page was a year old, and
    the search providers in use return no dates)."""

    _BODY = (
        "<article><p>"
        + "Koalice SPOLU po volbách řeší, kdo povede pravici a jak dál s ODS. " * 6
        + "</p></article>"
    )

    def _page(self, head: str) -> str:
        return f"<html><head>{head}</head><body>{self._BODY}</body></html>"

    def test_an_article_starts_with_its_publish_date(self) -> None:
        head = (
            '<meta property="og:type" content="article">'
            '<meta property="article:published_time" content="2025-10-06T08:00:00+02:00">'
        )
        assert extract_text_from_html(self._page(head)).startswith("Published: 2025-10-06")

    def test_a_page_that_is_not_an_article_gets_no_date(self) -> None:
        # Wikipedia and hub pages: their only dates are creation or copyright
        # years, which would make a maintained page look stale
        head = (
            '<meta property="og:type" content="website">'
            '<meta property="article:published_time" content="2009-06-11">'
        )
        assert "Published:" not in extract_text_from_html(self._page(head))

    def test_an_undated_article_gets_no_line(self) -> None:
        head = '<meta property="og:type" content="article">'
        assert "Published:" not in extract_text_from_html(self._page(head))

    def test_the_date_survives_truncation(self) -> None:
        head = (
            '<meta property="og:type" content="article">'
            '<meta property="article:published_time" content="2025-10-06">'
        )
        assert "Published: 2025-10-06" in extract_text_from_html(self._page(head), max_length=50)

    def test_dates_in_prose_are_not_parsed(self) -> None:
        # htmldate's prose search runs dateparser over all its ~200 languages,
        # ~30 MB that each worker kept for life (Oct 15 2026); articles state
        # their date in markup (21 of 21 sampled news articles)
        head = '<meta property="og:type" content="article">'
        page = self._page(head).replace("<article>", "<article><p>Vydáno 6. října 2025 v 8:00</p>")
        with patch.object(dateparser.DateDataParser, "get_date_data") as dateparser_call:
            extract_text_from_html(page)
        dateparser_call.assert_not_called()


@contextmanager
def _gc_paused() -> Iterator[None]:
    was_enabled = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        yield
    finally:
        if was_enabled:
            gc.enable()


def _live_tree_nodes() -> int:
    """Parsed-page nodes in memory, the root soup included (it is a Tag)."""
    return sum(1 for o in gc.get_objects() if isinstance(o, (Tag, NavigableString)))


class TestParsedTreesAreFreed:
    """A parsed page is freed when its function returns (Oct 14 2026: soups are
    reference cycles, so each fetched page waited for the cyclic GC - workers
    held dozens of whole pages at a time, and the heap they grew never shrank)."""

    _PRODUCT = (
        '<html><head><script type="application/ld+json">{"@type":"Product","name":"Wallet",'
        '"offers":{"price":"2490","priceCurrency":"CZK"}}</script></head>'
        "<body><nav>Menu</nav><p>Body text</p><script>x()</script></body></html>"
    )
    _PLAIN = "<html><body><nav>Menu</nav><p>Body text</p></body></html>"

    @pytest.mark.parametrize(
        ("parse", "html"),
        [
            (product_data_line, _PRODUCT),
            (product_data_line, _PLAIN),
            (_html_to_markdown, _PRODUCT),
        ],
        ids=["product-data-found", "product-data-absent", "markdown-fallback"],
    )
    def test_no_tree_outlives_the_call(self, parse: Callable[[str], str], html: str) -> None:
        with _gc_paused():
            before = _live_tree_nodes()
            result = parse(html)
            assert _live_tree_nodes() == before
        assert isinstance(result, str)
