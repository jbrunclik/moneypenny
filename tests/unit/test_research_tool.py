"""Tests for the composite research tool (search + fetch in one round)."""

import json
from unittest.mock import MagicMock, patch

from src.agent.tools.research import research
from src.config import Config


def _result(url: str, title: str = "T") -> dict[str, str]:
    return {"title": title, "url": url, "snippet": f"snippet for {url}"}


class TestSourceRanking:
    """Results are interleaved by rank across queries and deduplicated by URL:
    every query's best hit is read before any query's second one."""

    @patch("src.agent.tools.research.fetch_page_text", return_value=("page", None))
    @patch("src.agent.tools.research.search_web")
    def test_interleaves_by_rank_and_dedupes(
        self, mock_search: MagicMock, _fetch: MagicMock
    ) -> None:
        mock_search.side_effect = [
            [_result("https://a"), _result("https://b")],
            [_result("https://a"), _result("https://c")],
        ]

        parsed = json.loads(
            research.invoke({"question": "q", "queries": ["q1", "q2"], "max_sources": 3})
        )

        # Rank-0 results first across queries, dupes dropped
        assert [s["url"] for s in parsed["sources"]] == ["https://a", "https://b", "https://c"]

    @patch("src.agent.tools.research.fetch_page_text", return_value=("page", None))
    @patch("src.agent.tools.research.search_web")
    def test_failed_query_skipped(self, mock_search: MagicMock, _fetch: MagicMock) -> None:
        from src.services.search_adapters import SearchProviderError

        mock_search.side_effect = [
            SearchProviderError("rate limited"),
            [_result("https://a")],
        ]

        parsed = json.loads(
            research.invoke({"question": "q", "queries": ["q1", "q2"], "max_sources": 2})
        )

        assert [s["url"] for s in parsed["sources"]] == ["https://a"]


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

    @patch("src.agent.tools.research.fetch_page_text")
    @patch("src.agent.tools.research.search_web")
    def test_a_failed_fetch_is_replaced_by_the_next_candidate(
        self, mock_search: MagicMock, mock_fetch: MagicMock
    ) -> None:
        """Oct 2026 prod: 3 of 5 fetches failed (403/429) and the answer rested
        on the 2 pages left - 62 of 210 research calls in 30 days had a failure
        while untried candidates sat in "unfetched"."""
        mock_search.return_value = [_result(f"https://{c}") for c in "abcdef"]
        failing = {"https://b": "HTTP 429 when fetching https://b"}
        mock_fetch.side_effect = lambda url, _max: (
            (None, failing[url]) if url in failing else (f"page {url}", None)
        )

        parsed = json.loads(research.invoke({"question": "q", "max_sources": 2}))

        read = [s["url"] for s in parsed["sources"] if "content" in s]
        assert read == ["https://a", "https://c"]
        assert [s["url"] for s in parsed["sources"] if "error" in s] == ["https://b"]
        assert parsed["unfetched"][0]["url"] == "https://d"

    @patch("src.agent.tools.research.fetch_page_text")
    @patch("src.agent.tools.research.search_web")
    def test_replacements_are_fetched_once(
        self, mock_search: MagicMock, mock_fetch: MagicMock
    ) -> None:
        mock_search.return_value = [_result(f"https://{c}") for c in "abcdef"]
        mock_fetch.return_value = (None, "HTTP 403")

        parsed = json.loads(research.invoke({"question": "q", "max_sources": 2}))

        # One replacement wave, not a crawl: a, b, then c, d
        assert mock_fetch.call_count == 4
        assert [u["url"] for u in parsed["unfetched"]][:1] == ["https://e"]

    @patch("src.agent.tools.research.search_web")
    def test_all_searches_failed_returns_retriable_error(self, mock_search: MagicMock) -> None:
        from src.services.search_adapters import SearchProviderError

        mock_search.side_effect = SearchProviderError("down", retriable=True)

        parsed = json.loads(research.invoke({"question": "q"}))

        assert "error" in parsed
        assert parsed.get("retriable", True) is True  # no flag = retriable

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

    @patch("src.agent.tools.research.search_web")
    def test_nothing_found_is_a_note_not_an_error(self, mock_search: MagicMock) -> None:
        """Searches that ran fine but found nothing must not look like a
        failure (self-correction would push blind retries)."""
        mock_search.return_value = []

        parsed = json.loads(research.invoke({"question": "q"}))

        assert "error" not in parsed
        assert parsed["sources"] == []
        assert "no results" in parsed["note"].lower()

    @patch("src.agent.tools.research.fetch_page_text")
    @patch("src.agent.tools.research.search_web")
    def test_question_defaults_to_first_query(
        self, mock_search: MagicMock, mock_fetch: MagicMock
    ) -> None:
        """Every research ToolInvocationError in Sep 2026 was a call with
        queries but no question - accept it instead of failing the round."""
        mock_search.return_value = [_result("https://a")]
        mock_fetch.return_value = ("content", None)

        parsed = json.loads(research.invoke({"queries": ["trek domane specs", "synapse specs"]}))

        assert parsed["question"] == "trek domane specs"
        assert parsed["sources"]

    def test_empty_question_rejected(self) -> None:
        parsed = json.loads(research.invoke({"question": "  "}))
        assert "error" in parsed


class TestResearchDegradedSources:
    """On the ddgs fallback the ranking is weaker, so read more pages to
    compensate - the fetched content is what survives a bad snippet."""

    @patch("src.agent.tools.research.is_degraded", return_value=True)
    @patch("src.agent.tools.research.fetch_page_text")
    @patch("src.agent.tools.research.search_web")
    def test_reads_more_sources_while_degraded(
        self, mock_search: MagicMock, mock_fetch: MagicMock, _degraded: MagicMock
    ) -> None:
        mock_search.return_value = [_result(f"https://site{i}") for i in range(12)]
        mock_fetch.return_value = ("Page content here", None)

        parsed = json.loads(research.invoke({"question": "what is X?"}))

        assert len(parsed["sources"]) == Config.RESEARCH_DEGRADED_MAX_SOURCES

    @patch("src.agent.tools.research.is_degraded", return_value=False)
    @patch("src.agent.tools.research.fetch_page_text")
    @patch("src.agent.tools.research.search_web")
    def test_normal_default_when_providers_are_healthy(
        self, mock_search: MagicMock, mock_fetch: MagicMock, _degraded: MagicMock
    ) -> None:
        mock_search.return_value = [_result(f"https://site{i}") for i in range(12)]
        mock_fetch.return_value = ("Page content here", None)

        parsed = json.loads(research.invoke({"question": "what is X?"}))

        assert len(parsed["sources"]) == Config.RESEARCH_MAX_SOURCES

    @patch("src.agent.tools.research.is_degraded", return_value=True)
    @patch("src.agent.tools.research.fetch_page_text")
    @patch("src.agent.tools.research.search_web")
    def test_explicit_max_sources_still_wins(
        self, mock_search: MagicMock, mock_fetch: MagicMock, _degraded: MagicMock
    ) -> None:
        """The degraded bump is a default, not an override of the caller."""
        mock_search.return_value = [_result(f"https://site{i}") for i in range(12)]
        mock_fetch.return_value = ("Page content here", None)

        parsed = json.loads(research.invoke({"question": "what is X?", "max_sources": 2}))

        assert len(parsed["sources"]) == 2
