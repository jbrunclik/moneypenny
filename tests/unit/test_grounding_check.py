"""Unit tests for the post-answer grounding check (src/agent/grounding_check.py)."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent.grounding_check import append_unverified_note, collect_web_sources


def _tool(name: str, content: object, status: str = "success") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=f"id-{name}", name=name, status=status)


class TestCollectWebSources:
    def test_only_successful_web_tool_results_count(self) -> None:
        messages = [
            HumanMessage(content="where to buy"),
            _tool("web_search", "Shop A sells it for 100 CZK"),
            _tool("garmin_connect", '{"hrv": 41}'),
            _tool("fetch_url", "Error: 404", status="error"),
            AIMessage(content="answer"),
        ]

        assert collect_web_sources(messages, 1000) == "Shop A sells it for 100 CZK"

    def test_no_web_results_gives_empty_string(self) -> None:
        assert collect_web_sources([_tool("execute_code", "42")], 1000) == ""

    def test_multimodal_content_contributes_its_text_parts(self) -> None:
        content = [
            {"type": "text", "text": "PDF page: open 9-17"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]

        assert collect_web_sources([_tool("fetch_url", content)], 1000) == "PDF page: open 9-17"

    def test_cap_keeps_the_most_recent_results(self) -> None:
        messages = [_tool("web_search", "old " * 50), _tool("research", "newest result")]

        sources = collect_web_sources(messages, 20)

        # Filled newest-first (13 chars), the older result gets the remaining 7;
        # kept parts come back in original order
        assert sources == "old old" + "\n\n---\n\n" + "newest result"

    def test_single_result_longer_than_cap_is_truncated_not_dropped(self) -> None:
        sources = collect_web_sources([_tool("research", "x" * 500)], 100)

        assert sources == "x" * 100


class TestAppendUnverifiedNote:
    def test_no_items_leaves_answer_unchanged(self) -> None:
        assert append_unverified_note("Answer.", [], "cs") == "Answer."

    def test_czech_note(self) -> None:
        result = append_unverified_note("Odpověď.\n", ["VeloRama", "12 990 Kč"], "cs")

        assert result == (
            "Odpověď.\n\n_Neověřeno ve zdrojích, které jsem teď četl: VeloRama, 12 990 Kč._"
        )

    def test_english_note_for_other_and_unknown_languages(self) -> None:
        for language in ("en", "de", None):
            result = append_unverified_note("Answer.", ["VeloRama"], language)

            assert result == (
                "Answer.\n\n_Not confirmed in the sources I read for this answer: VeloRama._"
            )
