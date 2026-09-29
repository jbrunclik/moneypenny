"""Unit tests for HTML extraction and untrusted-content framing in src/agent/tools/web.py."""

from unittest.mock import patch

from src.agent.tools.web import (
    _extract_main_content,
    _extract_text_from_html,
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
        text = _extract_text_from_html(self._ARTICLE)
        assert "Sourdough Guide" in text
        assert "twenty-four hours" in text
        assert "Unrelated Menu Link" not in text
        assert "BoilerplateFooter" not in text

    def test_falls_back_when_main_content_too_short(self) -> None:
        """A link hub with no article body falls back to html2text."""
        with patch("src.agent.tools.web._extract_main_content", return_value="") as mock_main:
            text = _extract_text_from_html(
                "<html><body><ul><li>Headline A</li><li>Headline B</li></ul></body></html>"
            )
        mock_main.assert_called_once()
        assert "Headline A" in text  # came from the html2text fallback

    def test_main_content_used_when_sufficient(self) -> None:
        """A sufficiently long main-content extract is used verbatim (no fallback)."""
        long_text = "Real article body. " * 30  # > _MIN_MAIN_CONTENT_CHARS
        with patch("src.agent.tools.web._extract_main_content", return_value=long_text):
            text = _extract_text_from_html("<html><body><nav>NAVNOISE</nav></body></html>")
        assert "Real article body." in text
        assert "NAVNOISE" not in text  # fallback (which would keep nav) not used

    def test_trafilatura_failure_falls_back(self) -> None:
        """An exception inside trafilatura degrades to html2text, not a crash."""
        with patch("src.agent.tools.web.trafilatura.extract", side_effect=RuntimeError("boom")):
            text = _extract_text_from_html("<html><body><p>Fallback content here</p></body></html>")
        assert "Fallback content here" in text

    def test_truncates_at_limit(self) -> None:
        """Extracted text is capped at max_length with a truncation marker."""
        big = "word " * 500
        with patch("src.agent.tools.web._extract_main_content", return_value=big):
            text = _extract_text_from_html("<html></html>", max_length=100)
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
