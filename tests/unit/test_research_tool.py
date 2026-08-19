"""Tests for the composite research tool (search + fetch in one round)."""

import json
from unittest.mock import MagicMock, patch

from src.agent.tools.research import _ranked_unique_urls, research
from src.config import Config


def _result(url: str, title: str = "T") -> dict[str, str]:
    return {"title": title, "url": url, "snippet": f"snippet for {url}"}


class TestRankedUniqueUrls:
    @patch("src.agent.tools.research.search_web")
    def test_interleaves_by_rank_and_dedupes(self, mock_search: MagicMock) -> None:
        mock_search.side_effect = [
            [_result("https://a"), _result("https://b")],
            [_result("https://a"), _result("https://c")],
        ]

        ordered = _ranked_unique_urls(["q1", "q2"], per_query=2)

        # Rank-0 results first across queries, dupes dropped
        assert [r["url"] for r in ordered] == ["https://a", "https://b", "https://c"]

    @patch("src.agent.tools.research.search_web")
    def test_failed_query_skipped(self, mock_search: MagicMock) -> None:
        from src.utils.search_provider import SearchProviderError

        mock_search.side_effect = [
            SearchProviderError("rate limited"),
            [_result("https://a")],
        ]

        ordered = _ranked_unique_urls(["q1", "q2"], per_query=2)

        assert [r["url"] for r in ordered] == ["https://a"]


class TestResearchTool:
    @patch("src.agent.tools.research.fetch_page_text")
    @patch("src.agent.tools.research.search_web")
    def test_fetches_top_sources_and_reports(
        self, mock_search: MagicMock, mock_fetch: MagicMock
    ) -> None:
        mock_search.return_value = [_result(f"https://site{i}") for i in range(8)]
        mock_fetch.return_value = ("Page content here", None)

        parsed = json.loads(research.invoke({"question": "what is X?", "max_sources": 3}))

        assert parsed["question"] == "what is X?"
        assert len(parsed["sources"]) == 3
        assert all("content" in s for s in parsed["sources"])
        # Fetched content is framed as untrusted data
        assert "UNTRUSTED WEB CONTENT" in parsed["sources"][0]["content"]
        # Remaining candidates surface as snippet-only entries
        assert parsed["unfetched"]
        assert "_warning" in parsed

    @patch("src.agent.tools.research.fetch_page_text")
    @patch("src.agent.tools.research.search_web")
    def test_failed_fetch_degrades_to_error_entry(
        self, mock_search: MagicMock, mock_fetch: MagicMock
    ) -> None:
        mock_search.return_value = [_result("https://ok"), _result("https://broken")]
        mock_fetch.side_effect = [
            ("Good content", None),
            (None, "HTTP 403 when fetching https://broken"),
        ]

        parsed = json.loads(research.invoke({"question": "q", "max_sources": 2}))

        by_url = {s["url"]: s for s in parsed["sources"]}
        assert "content" in by_url["https://ok"]
        assert by_url["https://broken"]["error"] == "HTTP 403 when fetching https://broken"
        assert "snippet" in by_url["https://broken"]

    @patch("src.agent.tools.research.search_web")
    def test_all_searches_failed_returns_retriable_error(self, mock_search: MagicMock) -> None:
        from src.utils.search_provider import SearchProviderError

        mock_search.side_effect = SearchProviderError("down", retriable=True)

        parsed = json.loads(research.invoke({"question": "q"}))

        assert "error" in parsed
        assert parsed["retriable"] is True

    @patch("src.agent.tools.research.fetch_page_text")
    @patch("src.agent.tools.research.search_web")
    def test_queries_default_to_question_and_are_capped(
        self, mock_search: MagicMock, mock_fetch: MagicMock
    ) -> None:
        mock_search.return_value = [_result("https://a")]
        mock_fetch.return_value = ("content", None)

        research.invoke({"question": "the question"})
        assert mock_search.call_args_list[0][0][0] == "the question"

        mock_search.reset_mock()
        many = [f"q{i}" for i in range(Config.WEB_SEARCH_MAX_BATCH_QUERIES + 4)]
        research.invoke({"question": "q", "queries": many})
        assert mock_search.call_count == Config.WEB_SEARCH_MAX_BATCH_QUERIES

    def test_empty_question_rejected(self) -> None:
        parsed = json.loads(research.invoke({"question": "  "}))
        assert "error" in parsed
