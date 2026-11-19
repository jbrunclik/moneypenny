"""Weather forecasts for any place, from Yr.no (MET Norway).

The place resolves like the places tools do ("current" device fix -> saved
place -> Mapy.com geocode); the forecast goes through the cached Yr.no
client in src/utils/weather.py, keyed by coordinates rounded to 2 decimals
so nearby asks share one cache entry.
"""

import json
from datetime import datetime

from langchain_core.tools import tool

from src.agent.tools.context import get_location_context
from src.agent.tools.errors import tool_error
from src.agent.tools.places import resolve_point
from src.db.models import db
from src.db.models.timestamps import from_db
from src.services.planner.dates import local_date_of
from src.services.planner.weather import daily_weather
from src.utils.clock import to_local, utc_now
from src.utils.logging import get_logger
from src.utils.mapy import MapyError
from src.utils.weather import WeatherForecast, WeatherPeriod, get_weather_for_location

logger = get_logger(__name__)

WEATHER_SOURCE = "Yr.no (MET Norway)"
MAX_FORECAST_DAYS = 7
NEXT_HOURS = 12

# One forecast entry (a day or an hour) as it goes into the JSON result
ForecastEntry = dict[str, str | float | None]

_NO_DEVICE_FIX = (
    "Device location is not available - the user has not enabled location "
    'sharing on this device (Settings -> Location -> "Share device location with '
    'the assistant"). Ask which town they mean, or use a saved place.'
)


def _local_datetime(period: WeatherPeriod) -> datetime:
    """A forecast period's start as APP_TIMEZONE wall-clock time."""
    return to_local(from_db(period.time))


def _day_entries(forecast: WeatherForecast, days: int) -> list[ForecastEntry]:
    """One summary per local date, today first, at most `days`."""
    today = to_local(utc_now()).date().isoformat()
    winds: dict[str, float] = {}
    for period in forecast.periods:
        day = local_date_of(period.time)
        if day:
            key = day.isoformat()
            winds[key] = max(winds.get(key, 0.0), period.wind_speed)
    entries: list[ForecastEntry] = []
    for key, summary in sorted(daily_weather(forecast).items()):
        if key < today:
            continue
        entries.append(
            {
                "date": key,
                "low_c": summary.temperature_low,
                "high_c": summary.temperature_high,
                "rain_mm": round(summary.precipitation, 1),
                "wind_max_ms": winds.get(key, 0.0),
                "symbol": summary.symbol_code,
            }
        )
    return entries[:days]


def _next_hours(forecast: WeatherForecast) -> list[ForecastEntry]:
    """The next NEXT_HOURS periods from now, in local time."""
    now = utc_now()
    upcoming = [
        p
        for p in forecast.periods
        if _local_datetime(p) >= to_local(now).replace(minute=0, second=0, microsecond=0)
    ]
    return [
        {
            "time": _local_datetime(p).strftime("%H:%M"),
            "temp_c": p.temperature,
            "rain_mm": p.precipitation,
            "wind_ms": p.wind_speed,
            "symbol": p.symbol_code,
        }
        for p in upcoming[:NEXT_HOURS]
    ]


def _location_kind(location: str) -> str:
    return "current" if location.strip().lower() == "current" else "named"


@tool
def get_weather(location: str = "current", days: int = 3) -> str:
    """Get the weather forecast for a place: daily low/high, rain, wind, and the next hours.

    Use this for any weather question (today, tomorrow, the weekend, whether to
    take an umbrella) instead of a web search.

    Args:
        location: "current" (the user's device location), a saved place name
            ("home"), or a town or address ("Brno", "Špindlerův Mlýn")
        days: How many days to forecast, 1-7, starting today
    """
    days = max(1, min(MAX_FORECAST_DAYS, days))
    try:
        point = resolve_point(location)
    except MapyError as e:
        return tool_error(f"Could not look up '{location}': {e}")
    if point is None:
        if _location_kind(location) == "current" and get_location_context() is None:
            return tool_error(_NO_DEVICE_FIX, retriable=False)
        return tool_error(f"Could not find a place called '{location}'.", retriable=False)
    (lon, lat), label = point
    forecast = get_weather_for_location(f"{lat:.2f},{lon:.2f}", db=db)
    if forecast is None:
        return tool_error("The Yr.no forecast is unavailable right now.")
    entries = _day_entries(forecast, days)
    today = to_local(utc_now()).date().isoformat()
    result: dict[str, object] = {
        "place": label,
        "source": WEATHER_SOURCE,
        "fetched_at": forecast.fetched_at,
        "days": entries,
    }
    if entries and entries[0]["date"] == today:
        result["next_hours"] = _next_hours(forecast)
    logger.info(
        "Weather fetched",
        extra={
            "location_kind": _location_kind(location),
            "days": days,
            "fetched_at": forecast.fetched_at,
        },
    )
    return json.dumps(result, ensure_ascii=False)
