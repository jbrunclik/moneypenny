"""Tests for weather utility functions."""

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.utils.weather import (
    WeatherForecast,
    WeatherPeriod,
    fetch_weather_forecast,
    get_weather_for_location,
)


@pytest.fixture
def mock_yr_response() -> dict[str, Any]:
    """Mock Yr.no API response."""
    now = datetime.utcnow()
    return {
        "properties": {
            "timeseries": [
                {
                    "time": (now + timedelta(hours=i)).isoformat() + "Z",
                    "data": {
                        "instant": {
                            "details": {
                                "air_temperature": 5.0 + i * 0.5,
                                "wind_speed": 3.0,
                                "wind_from_direction": 180,
                                "cloud_area_fraction": 50,
                            }
                        },
                        "next_1_hours": {
                            "summary": {"symbol_code": "cloudy" if i % 2 else "clearsky_day"},
                            "details": {"precipitation_amount": 0.5 if i % 3 == 0 else 0},
                        },
                    },
                }
                for i in range(10)
            ]
        }
    }


def test_fetch_weather_forecast(mock_yr_response: dict[str, Any]) -> None:
    """Test fetching weather forecast from Yr.no API."""
    with patch("src.utils.weather.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_yr_response
        mock_get.return_value = mock_response

        forecast = fetch_weather_forecast(50.0755, 14.4378, "Prague")

        assert forecast.location == "Prague"
        assert forecast.latitude == 50.0755
        assert forecast.longitude == 14.4378
        assert len(forecast.periods) == 10
        assert isinstance(forecast.periods[0], WeatherPeriod)
        assert forecast.periods[0].temperature == 5.0
        assert forecast.periods[0].wind_speed == 3.0


def test_fetch_weather_forecast_api_error() -> None:
    """Test handling of API errors."""
    import requests

    with patch("src.utils.weather.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_get.return_value = mock_response

        with pytest.raises(requests.RequestException):
            fetch_weather_forecast(50.0755, 14.4378)


def test_get_weather_for_location_with_coordinates() -> None:
    """Test getting weather for location with lat,lon coordinates."""
    with patch("src.utils.weather.fetch_weather_forecast") as mock_fetch:
        mock_forecast = WeatherForecast(
            location="50.0755,14.4378",
            latitude=50.0755,
            longitude=14.4378,
            periods=[],
            fetched_at=datetime.utcnow().isoformat(),
        )
        mock_fetch.return_value = mock_forecast

        forecast = get_weather_for_location("50.0755, 14.4378", db=None)

        assert forecast is not None
        assert forecast.latitude == 50.0755
        assert forecast.longitude == 14.4378
        mock_fetch.assert_called_once()


def test_get_weather_for_location_with_cache() -> None:
    """Test that cached weather is returned."""
    mock_db = MagicMock()
    cached_data = {
        "location": "50.0755,14.4378",
        "latitude": 50.0755,
        "longitude": 14.4378,
        "periods": [],
        "fetched_at": datetime.utcnow().isoformat(),
    }
    mock_db.get_cached_weather.return_value = cached_data

    forecast = get_weather_for_location("50.0755,14.4378", db=mock_db, force_refresh=False)

    assert forecast is not None
    assert forecast.latitude == 50.0755
    mock_db.get_cached_weather.assert_called_once_with("50.0755,14.4378")


def test_get_weather_for_location_force_refresh() -> None:
    """Test that force_refresh bypasses cache."""
    mock_db = MagicMock()

    with patch("src.utils.weather.fetch_weather_forecast") as mock_fetch:
        mock_forecast = WeatherForecast(
            location="50.0755,14.4378",
            latitude=50.0755,
            longitude=14.4378,
            periods=[],
            fetched_at=datetime.utcnow().isoformat(),
        )
        mock_fetch.return_value = mock_forecast

        forecast = get_weather_for_location("50.0755,14.4378", db=mock_db, force_refresh=True)

        assert forecast is not None
        mock_db.get_cached_weather.assert_not_called()
        mock_fetch.assert_called_once()
        mock_db.cache_weather.assert_called_once()


def test_get_weather_for_location_invalid_format() -> None:
    """Test that invalid location format returns None."""
    forecast = get_weather_for_location("invalid", db=None)
    assert forecast is None


def test_get_weather_for_location_empty() -> None:
    """Test that empty location returns None."""
    forecast = get_weather_for_location("", db=None)
    assert forecast is None
