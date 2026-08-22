"""Sidebar preview snippets must strip markdown, not render it raw."""

from src.db.models.conversation import build_message_preview


class TestBuildMessagePreview:
    def test_plain_text_passes_through(self) -> None:
        assert build_message_preview("How about goulash?") == "How about goulash?"

    def test_collapses_whitespace(self) -> None:
        assert build_message_preview("a\n\nb\tc") == "a b c"

    def test_strips_bold_and_italic_markers(self) -> None:
        assert build_message_preview("**Vezmi klasický** *Broad Peak*") == (
            "Vezmi klasický Broad Peak"
        )
        assert build_message_preview("__bold__ and _italic_") == "bold and italic"

    def test_strips_headers_and_quotes(self) -> None:
        assert build_message_preview("## Plan\n> quoted line") == "Plan quoted line"

    def test_strips_inline_code_and_fences(self) -> None:
        assert build_message_preview("run `make dev` now") == "run make dev now"
        assert build_message_preview("```python\nprint('x')\n```") == "print('x')"

    def test_links_keep_their_text(self) -> None:
        assert build_message_preview("see [the docs](https://example.com)") == "see the docs"

    def test_strips_list_markers(self) -> None:
        assert build_message_preview("- first\n- second") == "first second"

    def test_truncates_long_content(self) -> None:
        preview = build_message_preview("word " * 100)
        assert preview is not None
        assert len(preview) <= 121
        assert preview.endswith("…")

    def test_none_and_empty(self) -> None:
        assert build_message_preview(None) is None
        assert build_message_preview("") is None
