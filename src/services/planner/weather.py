"""Weather for the planner dashboard: the forecast and its daily summaries."""

from typing import Any

from src.config import Config
from src.services.planner.dates import parse_datetime
from src.services.planner.models import PlannerWeather
from src.utils.logging import get_logger
from src.utils.weather import WeatherForecast, WeatherPeriod, get_weather_for_location

logger = get_logger(__name__)


def fetch_forecast(db: Any, force_refresh: bool) -> tuple[WeatherForecast | None, str | None]:
    """Fetch the configured location's forecast; (None, None) when none is configured."""
    if not Config.WEATHER_LOCATION:
        return None, None
    try:
        forecast = get_weather_for_location(
            Config.WEATHER_LOCATION,
            db=db,
            force_refresh=force_refresh,
        )
    except Exception as e:
        logger.exception(
            "Failed to fetch weather for planner",
            extra={"error": str(e), "location": Config.WEATHER_LOCATION},
        )
        return None, f"Weather error: {e}"
    return forecast, None


def _periods_by_date(periods: list[WeatherPeriod]) -> dict[str, list[WeatherPeriod]]:
    by_date: dict[str, list[WeatherPeriod]] = {}
    for period in periods:
        period_time = parse_datetime(period.time)
        if period_time:
            by_date.setdefault(period_time.strftime("%Y-%m-%d"), []).append(period)
    return by_date


def _day_weather(periods: list[WeatherPeriod]) -> PlannerWeather:
    """Summarize one day's forecast periods."""
    temps = [p.temperature for p in periods]
    # The middle symbol of the day (noon period preferred)
    symbols = [p.symbol_code for p in periods if p.symbol_code]
    symbol = symbols[len(symbols) // 2] if symbols else None

    temp_high = max(temps) if temps else None
    temp_low = min(temps) if temps else None
    total_precip = sum(p.precipitation for p in periods)

    summary_parts = []
    if temp_high and temp_low:
        summary_parts.append(f"{temp_low:.1f}-{temp_high:.1f}°C")
    if total_precip > 0:
        summary_parts.append(f"{total_precip:.1f}mm rain")

    return PlannerWeather(
        temperature_high=temp_high,
        temperature_low=temp_low,
        precipitation=total_precip,
        symbol_code=symbol,
        summary=", ".join(summary_parts) if summary_parts else "No data",
    )


def daily_weather(forecast: WeatherForecast) -> dict[str, PlannerWeather]:
    """The forecast summarized per date (YYYY-MM-DD)."""
    return {
        date_key: _day_weather(periods)
        for date_key, periods in _periods_by_date(forecast.periods).items()
    }
