"""Tests for the quota-aware search provider router.

Providers are tried in priority order (brave -> tavily -> exa -> ddgs);
a provider is skipped when unconfigured or over its monthly quota, and a
failing provider falls through to the next one. Usage counters live in
kv_store under a system sentinel user.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.utils.search_provider import (
    SearchProviderError,
    active_provider,
    get_monthly_usage,
    period_start,
    search_web,
    usage_key,
)


def _fake_db(usage: dict[str, int] | None = None) -> MagicMock:
    """A kv_store-shaped mock; `usage` maps usage keys to counts."""
    usage = usage or {}
    db = MagicMock()
    db.kv_get.side_effect = lambda _u, _ns, key: str(usage[key]) if key in usage else None
    db.kv_increment.side_effect = lambda _u, _ns, key, delta=1: usage.get(key, 0) + delta
    return db


def _no_keys() -> Any:  # noqa: ANN401
    """Patch stack: no paid provider configured."""
    return patch.multiple(
        Config,
        BRAVE_SEARCH_API_KEY="",
        TAVILY_API_KEY="",
        EXA_API_KEY="",
    )


class TestActiveProvider:
    def test_ddgs_when_nothing_configured(self) -> None:
        with _no_keys(), patch("src.utils.search_provider.db", _fake_db()):
            assert active_provider() == "ddgs"

    def test_brave_first_when_configured(self) -> None:
        with (
            patch.multiple(Config, BRAVE_SEARCH_API_KEY="bk", TAVILY_API_KEY="tk", EXA_API_KEY=""),
            patch("src.utils.search_provider.db", _fake_db()),
        ):
            assert active_provider() == "brave"

    def test_skips_provider_over_quota(self) -> None:
        usage = {usage_key("brave"): Config.SEARCH_QUOTA_BRAVE_MONTHLY}
        with (
            patch.multiple(Config, BRAVE_SEARCH_API_KEY="bk", TAVILY_API_KEY="tk", EXA_API_KEY=""),
            patch("src.utils.search_provider.db", _fake_db(usage)),
        ):
            assert active_provider() == "tavily"


class TestRouting:
    @patch("src.utils.search_provider._search_tavily")
    @patch("src.utils.search_provider._search_brave")
    def test_provider_error_falls_through_to_next(
        self, mock_brave: MagicMock, mock_tavily: MagicMock
    ) -> None:
        mock_brave.side_effect = SearchProviderError("rate limited", retriable=True)
        mock_tavily.return_value = [{"title": "T", "url": "https://a.example", "snippet": "S"}]
        with (
            patch.multiple(Config, BRAVE_SEARCH_API_KEY="bk", TAVILY_API_KEY="tk", EXA_API_KEY=""),
            patch("src.utils.search_provider.db", _fake_db()),
        ):
            results = search_web("q", 3)
        assert results[0]["url"] == "https://a.example"
        mock_tavily.assert_called_once()

    @patch("src.utils.search_provider._search_tavily")
    @patch("src.utils.search_provider._search_brave")
    def test_exhausted_quota_skips_without_calling(
        self, mock_brave: MagicMock, mock_tavily: MagicMock
    ) -> None:
        mock_tavily.return_value = [{"title": "T", "url": "https://a.example", "snippet": "S"}]
        usage = {usage_key("brave"): Config.SEARCH_QUOTA_BRAVE_MONTHLY}
        with (
            patch.multiple(Config, BRAVE_SEARCH_API_KEY="bk", TAVILY_API_KEY="tk", EXA_API_KEY=""),
            patch("src.utils.search_provider.db", _fake_db(usage)),
        ):
            results = search_web("q", 3)
        assert len(results) == 1
        mock_brave.assert_not_called()

    @patch("src.utils.search_provider._search_brave")
    def test_success_increments_monthly_usage(self, mock_brave: MagicMock) -> None:
        mock_brave.return_value = [{"title": "T", "url": "https://a.example", "snippet": "S"}]
        db = _fake_db()
        with (
            patch.multiple(Config, BRAVE_SEARCH_API_KEY="bk", TAVILY_API_KEY="", EXA_API_KEY=""),
            patch("src.utils.search_provider.db", db),
        ):
            search_web("q", 3)
        db.kv_increment.assert_called_once()
        assert db.kv_increment.call_args[0][2] == usage_key("brave")

    @patch("src.utils.search_provider._search_brave")
    def test_failed_call_does_not_bill(self, mock_brave: MagicMock) -> None:
        mock_brave.side_effect = SearchProviderError("boom")
        db = _fake_db()
        with (
            patch.multiple(Config, BRAVE_SEARCH_API_KEY="bk", TAVILY_API_KEY="", EXA_API_KEY=""),
            patch("src.utils.search_provider.db", db),
            patch("src.utils.search_provider._search_ddgs") as mock_ddgs,
        ):
            mock_ddgs.return_value = [{"title": "T", "url": "https://a", "snippet": "S"}]
            search_web("q", 3)
        # ddgs is unmetered; the failed brave call must not be billed
        db.kv_increment.assert_not_called()

    @patch("src.utils.search_provider._search_ddgs")
    @patch("src.utils.search_provider._search_brave")
    def test_all_providers_failing_raises_last_error(
        self, mock_brave: MagicMock, mock_ddgs: MagicMock
    ) -> None:
        mock_brave.side_effect = SearchProviderError("brave down", retriable=True)
        mock_ddgs.side_effect = SearchProviderError("ddgs down", retriable=True)
        with (
            patch.multiple(Config, BRAVE_SEARCH_API_KEY="bk", TAVILY_API_KEY="", EXA_API_KEY=""),
            patch("src.utils.search_provider.db", _fake_db()),
        ):
            with pytest.raises(SearchProviderError) as exc_info:
                search_web("q", 3)
        assert exc_info.value.retriable is True


class TestMonthlyUsage:
    def test_usage_key_includes_current_month(self) -> None:
        key = usage_key("brave")
        assert key.startswith("brave:")
        # YYYY-MM shape
        month = key.split(":", 1)[1]
        assert len(month) == 7 and month[4] == "-"

    def test_get_monthly_usage_defaults_to_zero(self) -> None:
        with patch("src.utils.search_provider.db", _fake_db()):
            assert get_monthly_usage("brave") == 0

    def test_get_monthly_usage_reads_counter(self) -> None:
        with patch("src.utils.search_provider.db", _fake_db({usage_key("brave"): 42})):
            assert get_monthly_usage("brave") == 42


class TestBraveSearch:
    @patch.object(Config, "BRAVE_SEARCH_API_KEY", "test-key")
    @patch("src.utils.search_provider.httpx.get")
    def test_maps_brave_results_to_contract(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "web": {
                "results": [
                    {"title": "T1", "url": "https://a.example", "description": "D1"},
                    {"title": "T2", "url": "https://b.example", "description": "D2"},
                ]
            }
        }
        mock_get.return_value = mock_response

        with patch("src.utils.search_provider.db", _fake_db()):
            results = search_web("test query", 2)

        assert results == [
            {"title": "T1", "url": "https://a.example", "snippet": "D1"},
            {"title": "T2", "url": "https://b.example", "snippet": "D2"},
        ]
        assert mock_get.call_args.kwargs["headers"]["X-Subscription-Token"] == "test-key"

    @patch.object(Config, "BRAVE_SEARCH_API_KEY", "test-key")
    @patch("src.utils.search_provider.httpx.get")
    def test_brave_caps_results(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "web": {
                "results": [{"title": f"T{i}", "url": f"https://{i}.example"} for i in range(10)]
            }
        }
        mock_get.return_value = mock_response

        with patch("src.utils.search_provider.db", _fake_db()):
            assert len(search_web("q", 3)) == 3


class TestTavilySearch:
    @patch("src.utils.search_provider.httpx.post")
    def test_maps_tavily_results_to_contract(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"title": "T1", "url": "https://a.example", "content": "C1"},
            ]
        }
        mock_post.return_value = mock_response

        with (
            patch.multiple(
                Config, BRAVE_SEARCH_API_KEY="", TAVILY_API_KEY="tvly-key", EXA_API_KEY=""
            ),
            patch("src.utils.search_provider.db", _fake_db()),
        ):
            results = search_web("q", 3)

        assert results == [{"title": "T1", "url": "https://a.example", "snippet": "C1"}]
        assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer tvly-key"

    @patch("src.utils.search_provider.httpx.post")
    def test_tavily_rate_limit_is_retriable(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_post.return_value = mock_response

        with (
            patch.multiple(
                Config, BRAVE_SEARCH_API_KEY="", TAVILY_API_KEY="tvly-key", EXA_API_KEY=""
            ),
            patch("src.utils.search_provider.db", _fake_db()),
            patch("src.utils.search_provider._search_ddgs") as mock_ddgs,
        ):
            mock_ddgs.return_value = []
            search_web("q", 3)
        # Fell through to ddgs after the 429
        mock_ddgs.assert_called_once()


class TestExaSearch:
    @patch("src.utils.search_provider.httpx.post")
    def test_maps_exa_results_to_contract(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"title": "T1", "url": "https://a.example", "text": "body text"},
            ]
        }
        mock_post.return_value = mock_response

        with (
            patch.multiple(
                Config, BRAVE_SEARCH_API_KEY="", TAVILY_API_KEY="", EXA_API_KEY="exa-key"
            ),
            patch("src.utils.search_provider.db", _fake_db()),
        ):
            results = search_web("q", 3)

        assert results == [{"title": "T1", "url": "https://a.example", "snippet": "body text"}]
        assert mock_post.call_args.kwargs["headers"]["x-api-key"] == "exa-key"

    @patch("src.utils.search_provider.httpx.post")
    def test_exa_out_of_credits_falls_through(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 402
        mock_post.return_value = mock_response

        with (
            patch.multiple(
                Config, BRAVE_SEARCH_API_KEY="", TAVILY_API_KEY="", EXA_API_KEY="exa-key"
            ),
            patch("src.utils.search_provider.db", _fake_db()),
            patch("src.utils.search_provider._search_ddgs") as mock_ddgs,
        ):
            mock_ddgs.return_value = []
            search_web("q", 3)
        mock_ddgs.assert_called_once()


class TestDdgsSearch:
    @patch("src.utils.search_provider.DDGS")
    def test_maps_ddgs_results_to_contract(self, mock_ddgs_class: MagicMock) -> None:
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = [
            {"title": "T1", "href": "https://a.example", "body": "B1"},
        ]
        mock_ddgs_class.return_value = mock_ddgs

        with _no_keys(), patch("src.utils.search_provider.db", _fake_db()):
            results = search_web("test query", 5)

        assert results == [{"title": "T1", "url": "https://a.example", "snippet": "B1"}]

    @patch("src.utils.search_provider.DDGS")
    def test_ddgs_rate_limit_raises_retriable(self, mock_ddgs_class: MagicMock) -> None:
        from ddgs.exceptions import RatelimitException

        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.side_effect = RatelimitException("rate limited")
        mock_ddgs_class.return_value = mock_ddgs

        with _no_keys(), patch("src.utils.search_provider.db", _fake_db()):
            with pytest.raises(SearchProviderError) as exc_info:
                search_web("q", 5)
        assert exc_info.value.retriable is True


class TestQuoteStrippingRetry:
    """Quoted operator queries often return nothing; retry unquoted inside
    the winning provider - one extra call instead of a full LLM round."""

    @patch("src.utils.search_provider.DDGS")
    def test_zero_results_with_quotes_retries_unquoted(self, mock_ddgs_class: MagicMock) -> None:
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.side_effect = [
            [],  # quoted query: nothing
            [{"title": "T", "href": "https://a.example", "body": "B"}],
        ]
        mock_ddgs_class.return_value = mock_ddgs

        with _no_keys(), patch("src.utils.search_provider.db", _fake_db()):
            results = search_web('"MacBook Air" "watt-hour" battery', 5)

        assert len(results) == 1
        assert mock_ddgs.text.call_count == 2
        retry_query = mock_ddgs.text.call_args_list[1][0][0]
        assert '"' not in retry_query
        assert "MacBook Air" in retry_query

    @patch("src.utils.search_provider.DDGS")
    def test_no_retry_without_quotes(self, mock_ddgs_class: MagicMock) -> None:
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = []
        mock_ddgs_class.return_value = mock_ddgs

        with _no_keys(), patch("src.utils.search_provider.db", _fake_db()):
            results = search_web("plain query", 5)

        assert results == []
        assert mock_ddgs.text.call_count == 1


class TestBillingPeriods:
    """Quotas reset per provider billing period, not calendar month."""

    def test_anchor_day_one_uses_calendar_month_key(self) -> None:
        from datetime import date

        assert period_start(1, date(2026, 8, 22)) == "2026-08"

    def test_day_on_or_after_anchor_starts_this_month(self) -> None:
        from datetime import date

        assert period_start(22, date(2026, 8, 22)) == "2026-08-22"
        assert period_start(22, date(2026, 8, 30)) == "2026-08-22"

    def test_day_before_anchor_belongs_to_previous_period(self) -> None:
        from datetime import date

        assert period_start(22, date(2026, 9, 10)) == "2026-08-22"
        assert period_start(22, date(2027, 1, 5)) == "2026-12-22"

    def test_anchor_clamped_to_month_length(self) -> None:
        from datetime import date

        # Anchor 31: February period starts on the 28th (2026 is not a leap year)
        assert period_start(31, date(2026, 3, 10)) == "2026-02-28"

    def test_usage_key_uses_provider_anchor(self) -> None:
        with patch.object(Config, "SEARCH_BILLING_DAY_TAVILY", 22):
            key = usage_key("tavily")
        assert key.startswith("tavily:")
        # Anchored providers get a full period-start date, not YYYY-MM
        assert len(key.split(":", 1)[1]) == 10


class TestDegradationAlert:
    """Falling back to ddgs while paid providers are configured pushes a
    once-per-day operator alert - otherwise quality degrades silently."""

    @staticmethod
    def _db_with_store(store: dict[str, str]) -> MagicMock:
        db = MagicMock()
        db.kv_get.side_effect = lambda _u, _ns, key: store.get(key)
        db.kv_set.side_effect = lambda _u, _ns, key, value: store.__setitem__(key, value)
        db.kv_increment.side_effect = lambda _u, _ns, key, delta=1: store.setdefault(key, "0")
        operator = MagicMock()
        operator.id = "op-user-id"
        db.get_user_by_email.return_value = operator
        return db

    @patch("src.utils.push.send_push_to_user")
    @patch("src.utils.search_provider._search_ddgs")
    def test_ddgs_fallback_with_paid_providers_alerts_operator(
        self, mock_ddgs: MagicMock, mock_push: MagicMock
    ) -> None:
        mock_ddgs.return_value = []
        usage = {usage_key("brave"): str(Config.SEARCH_QUOTA_BRAVE_MONTHLY)}
        with (
            patch.multiple(
                Config,
                BRAVE_SEARCH_API_KEY="bk",
                TAVILY_API_KEY="",
                EXA_API_KEY="",
                ALLOWED_EMAILS=["op@example.com"],
            ),
            patch("src.utils.search_provider.db", self._db_with_store(usage)),
        ):
            search_web("q", 3)
        mock_push.assert_called_once()
        assert mock_push.call_args[0][0] == "op-user-id"

    @patch("src.utils.push.send_push_to_user")
    @patch("src.utils.search_provider._search_ddgs")
    def test_alert_deduped_within_a_day(self, mock_ddgs: MagicMock, mock_push: MagicMock) -> None:
        mock_ddgs.return_value = []
        store = {usage_key("brave"): str(Config.SEARCH_QUOTA_BRAVE_MONTHLY)}
        with (
            patch.multiple(
                Config,
                BRAVE_SEARCH_API_KEY="bk",
                TAVILY_API_KEY="",
                EXA_API_KEY="",
                ALLOWED_EMAILS=["op@example.com"],
            ),
            patch("src.utils.search_provider.db", self._db_with_store(store)),
        ):
            search_web("q", 3)
            search_web("q2", 3)
        mock_push.assert_called_once()

    @patch("src.utils.push.send_push_to_user")
    @patch("src.utils.search_provider._search_ddgs")
    def test_no_alert_when_no_paid_provider_configured(
        self, mock_ddgs: MagicMock, mock_push: MagicMock
    ) -> None:
        mock_ddgs.return_value = []
        with (
            patch.multiple(Config, BRAVE_SEARCH_API_KEY="", TAVILY_API_KEY="", EXA_API_KEY=""),
            patch("src.utils.search_provider.db", self._db_with_store({})),
        ):
            search_web("q", 3)
        mock_push.assert_not_called()

    @patch("src.utils.push.send_push_to_user")
    @patch("src.utils.search_provider._search_brave")
    def test_no_alert_when_paid_provider_serves(
        self, mock_brave: MagicMock, mock_push: MagicMock
    ) -> None:
        mock_brave.return_value = [{"title": "T", "url": "https://a", "snippet": "S"}]
        with (
            patch.multiple(Config, BRAVE_SEARCH_API_KEY="bk", TAVILY_API_KEY="", EXA_API_KEY=""),
            patch("src.utils.search_provider.db", self._db_with_store({})),
        ):
            search_web("q", 3)
        mock_push.assert_not_called()
