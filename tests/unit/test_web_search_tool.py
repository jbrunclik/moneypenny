"""Unit tests for the web_search tool in src/agent/tools/web.py."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

from src.agent.tools import web_search
from src.config import Config


class TestWebSearchDegradedNotice:
    """While results come from ddgs, the model is told so on the tool RESULT,
    where efficiency directives actually land, so it can escalate to research
    instead of re-searching against the same fallback.

    The notice is driven by which provider ANSWERED, never by availability
    sampled before the search - a provider can look available, fail, and fall
    through to ddgs inside the same call.
    """

    _RESULTS = [{"title": "T", "url": "https://a.example", "snippet": "S"}]

    @staticmethod
    def _metered_configured() -> Any:
        return patch.multiple(
            Config,
            BRAVE_SEARCH_API_KEY="bk",
            TAVILY_API_KEY="",
            EXA_API_KEY="",
            LINKUP_API_KEY="",
        )

    @patch("src.agent.tools.web.search_web_detailed")
    def test_ddgs_served_result_points_at_research(self, mock_search: MagicMock) -> None:
        mock_search.return_value = (self._RESULTS, "ddgs")
        with self._metered_configured():
            parsed = json.loads(web_search.invoke({"query": "q"}))
        assert "research" in parsed["_degraded"]

    @patch("src.agent.tools.web.search_web_detailed")
    def test_no_notice_while_a_metered_provider_serves(self, mock_search: MagicMock) -> None:
        mock_search.return_value = (self._RESULTS, "brave")
        with self._metered_configured():
            parsed = json.loads(web_search.invoke({"query": "q"}))
        assert "_degraded" not in parsed

    @patch("src.agent.tools.web.search_web_detailed")
    def test_no_notice_when_no_metered_provider_is_configured(self, mock_search: MagicMock) -> None:
        """A dev box without keys runs on ddgs by design, not by degradation."""
        mock_search.return_value = (self._RESULTS, "ddgs")
        with patch.multiple(
            Config,
            BRAVE_SEARCH_API_KEY="",
            TAVILY_API_KEY="",
            EXA_API_KEY="",
            LINKUP_API_KEY="",
        ):
            parsed = json.loads(web_search.invoke({"query": "q"}))
        assert "_degraded" not in parsed

    @patch("src.agent.tools.web.search_web_detailed")
    def test_batched_calls_carry_the_notice_too(self, mock_search: MagicMock) -> None:
        mock_search.return_value = (self._RESULTS, "ddgs")
        with self._metered_configured():
            parsed = json.loads(web_search.invoke({"queries": ["alpha", "beta"]}))
        assert "_degraded" in parsed

    @patch("src.agent.tools.web.search_web_detailed")
    def test_served_by_bookkeeping_never_reaches_the_model(self, mock_search: MagicMock) -> None:
        mock_search.return_value = (self._RESULTS, "ddgs")
        with self._metered_configured():
            parsed = json.loads(web_search.invoke({"query": "q"}))
            batched = json.loads(web_search.invoke({"queries": ["a", "b"]}))
        assert "_served_by" not in parsed
        assert all("_served_by" not in search for search in batched["searches"])

    @patch("src.utils.search_provider._search_ddgs")
    @patch("src.utils.search_provider._search_brave")
    def test_fallback_during_the_call_is_still_flagged(
        self, mock_brave: MagicMock, mock_ddgs: MagicMock
    ) -> None:
        """The notice must describe what actually served, not a pre-call guess.

        Brave has quota and looks available when the call starts, so a check
        taken before searching says "not degraded". It then fails and the
        router falls through to ddgs inside this same call - which is the
        exact case the notice exists for.
        """
        from src.utils.search_provider import SearchProviderError

        mock_brave.side_effect = SearchProviderError("503", retriable=True)
        mock_ddgs.return_value = self._RESULTS
        fake_db = MagicMock()
        fake_db.kv_get.return_value = None
        fake_db.kv_increment.return_value = 1
        with (
            self._metered_configured(),
            patch("src.utils.search_provider.db", fake_db),
        ):
            parsed = json.loads(web_search.invoke({"query": "q"}))
        assert "_degraded" in parsed


class TestWebSearch:
    """Tests for web_search tool (provider mocked at the search_web seam)."""

    @patch("src.agent.tools.web.search_web_detailed")
    def test_returns_search_results(self, mock_search: MagicMock) -> None:
        """Should return formatted search results."""
        mock_search.return_value = (
            [
                {"title": "Result 1", "url": "https://example.com/1", "snippet": "Snippet 1"},
                {"title": "Result 2", "url": "https://example.com/2", "snippet": "Snippet 2"},
            ],
            "brave",
        )

        result = web_search.invoke({"query": "test query"})
        parsed = json.loads(result)

        assert parsed["query"] == "test query"
        assert len(parsed["results"]) == 2
        assert parsed["results"][0]["title"] == "Result 1"
        assert parsed["results"][0]["url"] == "https://example.com/1"
        assert parsed["results"][0]["snippet"] == "Snippet 1"
        # Results are flagged as untrusted external content
        assert "untrusted" in parsed["_warning"].lower()

    @patch("src.agent.tools.web.search_web_detailed")
    def test_handles_empty_results(self, mock_search: MagicMock) -> None:
        """Should handle no search results."""
        mock_search.return_value = ([], "brave")

        result = web_search.invoke({"query": "obscure query xyz123"})
        parsed = json.loads(result)

        assert parsed["results"] == []
        # Empty is a legitimate outcome, not a failure: an "error" key would
        # trigger self-correction retry guidance (the most common tool
        # "error" in Sep 2026, 29 of them, driving blind retries)
        assert "error" not in parsed
        assert "no results" in parsed["note"].lower()

    @patch("src.agent.tools.web.search_web_detailed")
    def test_respects_num_results_limit(self, mock_search: MagicMock) -> None:
        """Should pass num_results through to the provider."""
        mock_search.return_value = ([], "brave")

        web_search.invoke({"query": "test", "num_results": 3})

        mock_search.assert_called_once_with("test", 3)

    @patch("src.agent.tools.web.search_web_detailed")
    def test_caps_num_results_at_10(self, mock_search: MagicMock) -> None:
        """Should cap num_results at 10."""
        mock_search.return_value = ([], "brave")

        web_search.invoke({"query": "test", "num_results": 100})

        mock_search.assert_called_once_with("test", 10)

    @patch("src.agent.tools.web.search_web_detailed")
    def test_handles_search_exception(self, mock_search: MagicMock) -> None:
        """Provider errors become an error result, with the retriable hint."""
        from src.utils.search_provider import SearchProviderError

        mock_search.side_effect = SearchProviderError("Search failed", retriable=False)

        result = web_search.invoke({"query": "test"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert parsed["results"] == []
        assert parsed["retriable"] is False


class TestWebSearchBatching:
    """Tests for batched multi-query web_search calls."""

    _ONE_RESULT = [{"title": "T", "url": "https://example.com", "snippet": "S"}]
    # search_web_detailed returns (results, served_by)
    _ONE_SERVED = (_ONE_RESULT, "brave")

    @patch("src.agent.tools.web.search_web_detailed")
    def test_multiple_queries_in_one_call(self, mock_search: MagicMock) -> None:
        """Batched queries run together and return a searches array."""
        mock_search.return_value = self._ONE_SERVED

        result = web_search.invoke({"queries": ["alpha", "beta", "gamma"]})
        parsed = json.loads(result)

        assert [s["query"] for s in parsed["searches"]] == ["alpha", "beta", "gamma"]
        assert all(s["results"] for s in parsed["searches"])
        assert mock_search.call_count == 3
        assert "untrusted" in parsed["_warning"].lower()

    @patch("src.agent.tools.web.search_web_detailed")
    def test_query_and_queries_merge_with_dedup(self, mock_search: MagicMock) -> None:
        """query + queries merge, blanks and duplicates dropped, order kept."""
        mock_search.return_value = self._ONE_SERVED

        result = web_search.invoke({"query": "alpha", "queries": ["alpha", " ", "beta"]})
        parsed = json.loads(result)

        assert [s["query"] for s in parsed["searches"]] == ["alpha", "beta"]
        assert mock_search.call_count == 2

    @patch("src.agent.tools.web.search_web_detailed")
    def test_batch_capped_with_note(self, mock_search: MagicMock) -> None:
        """Batches above the cap are truncated and the response says so."""
        mock_search.return_value = self._ONE_SERVED

        queries = [f"q{i}" for i in range(Config.WEB_SEARCH_MAX_BATCH_QUERIES + 3)]
        result = web_search.invoke({"queries": queries})
        parsed = json.loads(result)

        assert len(parsed["searches"]) == Config.WEB_SEARCH_MAX_BATCH_QUERIES
        assert mock_search.call_count == Config.WEB_SEARCH_MAX_BATCH_QUERIES
        assert "3 queries were dropped" in parsed["note"]

    @patch("src.agent.tools.web.search_web_detailed")
    def test_single_query_keeps_legacy_shape(self, mock_search: MagicMock) -> None:
        """A one-element queries list returns the flat single-query shape."""
        mock_search.return_value = self._ONE_SERVED

        result = web_search.invoke({"queries": ["only one"]})
        parsed = json.loads(result)

        assert parsed["query"] == "only one"
        assert "searches" not in parsed

    @patch("src.agent.tools.web.search_web_detailed")
    def test_per_query_error_does_not_break_batch(self, mock_search: MagicMock) -> None:
        """A rate-limited query reports its error; the rest still succeed."""
        from src.utils.search_provider import SearchProviderError

        # Keyed on the query, not call order: batched queries run in parallel
        # threads, so a positional side_effect list is consumed nondeterministically.
        def _by_query(query: str, _num: int) -> tuple[list[dict[str, str]], str]:
            if query == "limited":
                raise SearchProviderError("slow down", retriable=True)
            return self._ONE_SERVED

        mock_search.side_effect = _by_query

        result = web_search.invoke({"queries": ["good", "limited"]})
        parsed = json.loads(result)

        assert parsed["searches"][0]["results"]
        assert "error" in parsed["searches"][1]

    def test_no_query_at_all_returns_error(self) -> None:
        """Calling with neither query nor queries is an error, not a crash."""
        parsed = json.loads(web_search.invoke({"query": ""}))
        assert "error" in parsed


def test_parallel_searches_keep_the_request_id() -> None:
    """Search logs had no request id (pool threads lost the context), so a
    quota alert could not be traced to the turns that spent it (Oct 2026)."""
    from unittest.mock import patch

    from src.agent.tools import web
    from src.utils.logging import get_request_id, request_id_var

    seen: list[str | None] = []

    def fake_search_one(query: str, num_results: int) -> dict[str, object]:
        seen.append(get_request_id())
        return {"query": query, "results": []}

    token = request_id_var.set("req-abc")
    try:
        with patch.object(web, "_search_one", fake_search_one):
            web._search_many(["a", "b", "c"], 3)
    finally:
        request_id_var.reset(token)

    assert seen == ["req-abc", "req-abc", "req-abc"]
