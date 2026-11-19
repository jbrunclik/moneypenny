"""Tests for the get_weather agent tool (src/agent/tools/weather.py)."""

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

from src.agent.tools.weather import get_weather
from src.utils.weather import WeatherForecast, WeatherPeriod

# Nov 19 2026 22:00 UTC is Nov 19 23:00 in Prague; 23:30 UTC is already Nov 20
_NOW = datetime(2026, 11, 19, 22, 0, tzinfo=UTC)


def _period(time: str, temp: float, rain: float = 0.0, wind: float = 2.0) -> WeatherPeriod:
    return WeatherPeriod(
        time=time,
        temperature=temp,
        precipitation=rain,
        wind_speed=wind,
        wind_direction=None,
        cloud_coverage=None,
        symbol_code="cloudy",
        summary="",
    )


def _forecast() -> WeatherForecast:
    return WeatherForecast(
        location="49.20,16.61",
        latitude=49.2,
        longitude=16.61,
        periods=[
            _period("2026-11-19T22:00:00Z", 4.0, rain=0.5),
            _period("2026-11-19T23:30:00Z", 3.0, wind=6.5),  # Nov 20 locally
            _period("2026-11-20T11:00:00Z", 9.0, rain=1.0, wind=4.0),
            _period("2026-11-21T11:00:00Z", 7.0),
        ],
        fetched_at="2026-11-19T21:50:00Z",
    )


def _call(args: dict[str, Any]) -> dict[str, Any]:
    with patch("src.agent.tools.weather.utc_now", return_value=_NOW):
        return json.loads(get_weather.invoke(args))


@patch("src.agent.tools.weather.get_weather_for_location", return_value=_forecast())
@patch("src.agent.tools.weather.resolve_point", return_value=((16.6068, 49.1951), "Brno"))
def test_daily_summary_fields(mock_resolve: MagicMock, mock_fetch: MagicMock) -> None:
    result = _call({"location": "Brno", "days": 2})
    assert result["place"] == "Brno"
    assert result["source"] == "Yr.no (MET Norway)"
    tomorrow = result["days"][1]
    assert tomorrow == {
        "date": "2026-11-20",
        "low_c": 3.0,
        "high_c": 9.0,
        "rain_mm": 1.0,
        "wind_max_ms": 6.5,
        "symbol": "cloudy",
    }


@patch("src.agent.tools.weather.get_weather_for_location", return_value=_forecast())
@patch("src.agent.tools.weather.resolve_point", return_value=((16.6068, 49.1951), "Brno"))
def test_days_are_local_dates(mock_resolve: MagicMock, mock_fetch: MagicMock) -> None:
    dates = [day["date"] for day in _call({"location": "Brno", "days": 3})["days"]]
    assert dates == ["2026-11-19", "2026-11-20", "2026-11-21"]


@patch("src.agent.tools.weather.get_weather_for_location", return_value=_forecast())
@patch("src.agent.tools.weather.resolve_point", return_value=((16.6068, 49.1951), "Brno"))
def test_coordinates_rounded_for_the_cache(mock_resolve: MagicMock, mock_fetch: MagicMock) -> None:
    _call({"location": "Brno"})
    assert mock_fetch.call_args.args[0] == "49.20,16.61"


@patch("src.agent.tools.weather.get_weather_for_location", return_value=_forecast())
@patch("src.agent.tools.weather.resolve_point", return_value=((16.6068, 49.1951), "Brno"))
def test_hourly_only_when_today_in_range(mock_resolve: MagicMock, mock_fetch: MagicMock) -> None:
    result = _call({"location": "Brno", "days": 1})
    assert [hour["time"] for hour in result["next_hours"]][:2] == ["23:00", "00:30"]


@patch("src.agent.tools.weather.get_weather_for_location", return_value=_forecast())
@patch("src.agent.tools.weather.resolve_point", return_value=((16.6068, 49.1951), "Brno"))
def test_days_clamped(mock_resolve: MagicMock, mock_fetch: MagicMock) -> None:
    assert len(_call({"location": "Brno", "days": 0})["days"]) == 1
    assert len(_call({"location": "Brno", "days": 30})["days"]) == 3  # all the fake has


@patch("src.agent.tools.weather.resolve_point", return_value=None)
@patch("src.agent.tools.weather.get_location_context", return_value=None)
def test_current_without_fix(mock_loc: MagicMock, mock_resolve: MagicMock) -> None:
    result = _call({"location": "current"})
    assert result["retriable"] is False
    assert "Share device location" in result["error"]


@patch("src.agent.tools.weather.resolve_point", return_value=None)
def test_unknown_place(mock_resolve: MagicMock) -> None:
    result = _call({"location": "Atlantis"})
    assert result["retriable"] is False
    assert "Atlantis" in result["error"]


@patch("src.agent.tools.weather.get_weather_for_location", return_value=None)
@patch("src.agent.tools.weather.resolve_point", return_value=((16.6068, 49.1951), "Brno"))
def test_forecast_unavailable(mock_resolve: MagicMock, mock_fetch: MagicMock) -> None:
    result = _call({"location": "Brno"})
    assert "error" in result
    assert result.get("retriable", True) is True


class TestToolSchema:
    """A type-less parameter breaks every chat that binds the tool."""

    def test_every_param_has_a_concrete_type(self) -> None:
        for name, schema in get_weather.args.items():
            assert "type" in schema or "anyOf" in schema, name
