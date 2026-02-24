"""Unit tests for currency rate update script."""

from unittest.mock import MagicMock, patch

import httpx

from scripts.update_currency_rates import fetch_rates, get_existing_rates, main


class TestFetchRates:
    """Test the fetch_rates function."""

    def _mock_response(self, json_data: dict, status_code: int = 200) -> MagicMock:
        """Create a mock httpx response."""
        resp = MagicMock()
        resp.json.return_value = json_data
        resp.status_code = status_code
        resp.raise_for_status.return_value = None
        return resp

    @patch("scripts.update_currency_rates.httpx.Client")
    def test_fetch_rates_success(self, mock_client_cls):
        """Test successful rate fetching returns filtered rates."""
        mock_resp = self._mock_response(
            {
                "result": "success",
                "rates": {"USD": 1.0, "CZK": 23.5, "EUR": 0.92, "GBP": 0.79, "JPY": 150.0},
            }
        )
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(get=MagicMock(return_value=mock_resp))
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = fetch_rates()

        assert result is not None
        assert result["USD"] == 1.0
        assert result["CZK"] == 23.5
        assert result["EUR"] == 0.92
        assert result["GBP"] == 0.79
        assert "JPY" not in result  # Not in TARGET_CURRENCIES

    @patch("scripts.update_currency_rates.httpx.Client")
    def test_fetch_rates_api_error(self, mock_client_cls):
        """Test that API error response returns None."""
        mock_resp = self._mock_response({"result": "error", "error-type": "unsupported-code"})
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(get=MagicMock(return_value=mock_resp))
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = fetch_rates()

        assert result is None

    @patch("scripts.update_currency_rates.httpx.Client")
    def test_fetch_rates_missing_rates(self, mock_client_cls):
        """Test that missing rates key returns None."""
        mock_resp = self._mock_response({"result": "success"})
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(get=MagicMock(return_value=mock_resp))
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = fetch_rates()

        assert result is None

    @patch("scripts.update_currency_rates.httpx.Client")
    def test_fetch_rates_timeout(self, mock_client_cls):
        """Test that timeout returns None."""
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.TimeoutException("timed out")
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = fetch_rates()

        assert result is None

    @patch("scripts.update_currency_rates.httpx.Client")
    def test_fetch_rates_http_error(self, mock_client_cls):
        """Test that HTTP error returns None."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_resp
        )
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = fetch_rates()

        assert result is None

    @patch("scripts.update_currency_rates.httpx.Client")
    def test_fetch_rates_missing_currency(self, mock_client_cls):
        """Test that missing target currency produces partial dict."""
        mock_resp = self._mock_response(
            {
                "result": "success",
                "rates": {"USD": 1.0, "CZK": 23.5, "EUR": 0.92},
                # GBP missing from API response
            }
        )
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=MagicMock(get=MagicMock(return_value=mock_resp))
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = fetch_rates()

        assert result is not None
        assert "GBP" not in result
        assert result["CZK"] == 23.5
        assert result["USD"] == 1.0


class TestGetExistingRates:
    """Test the get_existing_rates function."""

    @patch("scripts.update_currency_rates.db")
    def test_returns_db_rates(self, mock_db):
        """Test that DB rates are returned when available."""
        mock_db.get_currency_rates.return_value = {"USD": 1.0, "CZK": 24.0}

        result = get_existing_rates()

        assert result == {"USD": 1.0, "CZK": 24.0}

    @patch("scripts.update_currency_rates.db")
    @patch("scripts.update_currency_rates.Config")
    def test_falls_back_to_config(self, mock_config, mock_db):
        """Test that Config fallback is used when DB returns None."""
        mock_db.get_currency_rates.return_value = None
        mock_config.CURRENCY_RATES = {"USD": 1.0, "CZK": 23.0}

        result = get_existing_rates()

        assert result == {"USD": 1.0, "CZK": 23.0}


class TestMain:
    """Test the main function."""

    @patch("scripts.update_currency_rates.db")
    @patch("scripts.update_currency_rates.fetch_rates")
    @patch("scripts.update_currency_rates.get_existing_rates")
    def test_main_success(self, mock_existing, mock_fetch, mock_db):
        """Test main returns 0 and saves rates on success."""
        mock_existing.return_value = {"USD": 1.0, "CZK": 23.0}
        mock_fetch.return_value = {"USD": 1.0, "CZK": 23.5, "EUR": 0.92, "GBP": 0.79}

        result = main()

        assert result == 0
        mock_db.set_currency_rates.assert_called_once_with(
            {"USD": 1.0, "CZK": 23.5, "EUR": 0.92, "GBP": 0.79}
        )

    @patch("scripts.update_currency_rates.db")
    @patch("scripts.update_currency_rates.fetch_rates")
    @patch("scripts.update_currency_rates.get_existing_rates")
    def test_main_fetch_failure(self, mock_existing, mock_fetch, mock_db):
        """Test main returns 1 and does NOT save when fetch fails."""
        mock_existing.return_value = {"USD": 1.0, "CZK": 23.0}
        mock_fetch.return_value = None

        result = main()

        assert result == 1
        mock_db.set_currency_rates.assert_not_called()
