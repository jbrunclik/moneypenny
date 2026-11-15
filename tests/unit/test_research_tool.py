"""Tests for the composite research tool (search + fetch in one round)."""

import json
from unittest.mock import MagicMock, patch

import pytest

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
        by_query = {
            "q1": [_result("https://a"), _result("https://b")],
            "q2": [_result("https://a"), _result("https://c")],
        }
        mock_search.side_effect = lambda query, _n: by_query[query]  # searches run in parallel

        parsed = json.loads(
            research.invoke({"question": "q", "queries": ["q1", "q2"], "max_sources": 3})
        )

        # Rank-0 results first across queries, dupes dropped
        assert [s["url"] for s in parsed["sources"]] == ["https://a", "https://b", "https://c"]

    @patch("src.agent.tools.research.fetch_page_text", return_value=("page", None))
    @patch("src.agent.tools.research.search_web")
    def test_failed_query_skipped(self, mock_search: MagicMock, _fetch: MagicMock) -> None:
        from src.services.search_adapters import SearchProviderError

        def search(query: str, _n: int) -> list[dict[str, str]]:
            if query == "q1":
                raise SearchProviderError("rate limited")
            return [_result("https://a")]

        mock_search.side_effect = search

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
        mock_fetch.side_effect = lambda url, _max, **_: (
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


class TestResearchSpeed:
    """Searches run in parallel and a page gets RESEARCH_FETCH_TIMEOUT_SECONDS
    (one slow page held research 90 s; Nov 15 2026 audit)."""

    @patch("src.agent.tools.research.fetch_page_text", return_value=("page", None))
    @patch("src.agent.tools.research.search_web")
    def test_the_searches_run_at_once(self, mock_search: MagicMock, _fetch: MagicMock) -> None:
        import threading

        both_waiting = threading.Barrier(2, timeout=5)

        def search(query: str, _n: int) -> list[dict[str, str]]:
            both_waiting.wait()  # breaks (and fails the call) if run one after another
            return [_result(f"https://{query}")]

        mock_search.side_effect = search
        parsed = json.loads(research.invoke({"question": "q", "queries": ["a", "b"]}))
        assert {s["url"] for s in parsed["sources"]} == {"https://a", "https://b"}

    @patch("src.agent.tools.research.fetch_page_text", return_value=("page", None))
    @patch("src.agent.tools.research.search_web")
    def test_every_search_failing_is_an_error(
        self, mock_search: MagicMock, _fetch: MagicMock
    ) -> None:
        from src.services.search_adapters import SearchProviderError

        mock_search.side_effect = SearchProviderError("down")
        result = research.invoke({"question": "q", "queries": ["a", "b"]})
        assert "All searches failed" in result

    @patch("src.agent.tools.research.fetch_page_text", return_value=("page", None))
    @patch("src.agent.tools.research.search_web", return_value=[_result("https://a")])
    def test_a_page_gets_a_short_timeout(self, _search: MagicMock, fetch: MagicMock) -> None:
        research.invoke({"question": "q"})
        assert fetch.call_args.kwargs["timeout"] == Config.RESEARCH_FETCH_TIMEOUT_SECONDS == 15

    @patch("src.agent.tools.research.fetch_page_text", return_value=("page", None))
    @patch("src.agent.tools.research.search_web", return_value=[_result("https://a")])
    def test_the_log_says_where_the_time_went(self, _search: MagicMock, _fetch: MagicMock) -> None:
        import importlib

        research_mod = importlib.import_module("src.agent.tools.research")

        with patch.object(research_mod.logger, "info") as info:
            research.invoke({"question": "q"})
        [extra] = [
            c.kwargs["extra"] for c in info.call_args_list if c.args[0] == "research completed"
        ]
        assert isinstance(extra["search_ms"], int)
        assert isinstance(extra["fetch_ms"], int)


class TestResearchPageDeadline:
    """A page that drips slower than httpx's per-read timeout cannot hold
    research past its wall-clock deadline (final review minor)."""

    @patch("src.agent.tools.research.search_web")
    @patch("src.agent.tools.research.fetch_page_text")
    def test_a_hung_page_is_given_up_on(
        self, mock_fetch: MagicMock, mock_search: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import threading
        import time

        release = threading.Event()
        mock_search.return_value = [_result("https://slow"), _result("https://fast")]

        def fetch(url: str, _max: int, **_: object) -> tuple[str | None, str | None]:
            if url == "https://slow":
                release.wait(10)
            return f"page {url}", None

        mock_fetch.side_effect = fetch
        monkeypatch.setattr(Config, "RESEARCH_PAGE_DEADLINE_SECONDS", 0.5)
        started = time.monotonic()
        try:
            parsed = json.loads(research.invoke({"question": "q", "max_sources": 2}))
        finally:
            release.set()
        assert time.monotonic() - started < 5
        by_url = {s["url"]: s for s in parsed["sources"]}
        assert "content" in by_url["https://fast"]
        assert "timed out" in by_url["https://slow"]["error"]

    def test_the_deadline_covers_a_direct_read_and_an_exa_read(self) -> None:
        assert Config.RESEARCH_PAGE_DEADLINE_SECONDS == (
            Config.RESEARCH_FETCH_TIMEOUT_SECONDS + Config.WEB_EXTRACT_TIMEOUT_SECONDS
        )
