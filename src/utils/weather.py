"""Weather utilities for fetching forecast data from Yr.no API.

Yr.no (Norwegian Meteorological Institute) provides free weather data
via their API. The data is cached in SQLite with a 6-hour TTL since
weather forecasts don't change that frequently.

API Documentation: https://api.met.no/weatherapi/locationforecast/2.0/
Terms of Service: https://api.met.no/doc/TermsOfService

The API requires:
- A proper User-Agent header (identifying your application)
- Latitude and longitude coordinates
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import requests

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class WeatherPeriod:
    """Weather forecast for a specific time period."""

    time: str  # ISO datetime
    temperature: float  # Celsius
    precipitation: float  # mm
    wind_speed: float  # m/s
    wind_direction: float | None  # degrees
    cloud_coverage: float | None  # percentage (0-100)
    symbol_code: str | None  # Weather symbol code (e.g., "clearsky_day", "rain")
    summary: str  # Human-readable summary


@dataclass
class WeatherForecast:
    """Complete weather forecast data."""

    location: str  # Location name or "lat,lon"
    latitude: float
    longitude: float
    periods: list[WeatherPeriod] = field(default_factory=list)
    fetched_at: str = ""  # ISO timestamp


def _build_summary(period_data: dict[str, Any]) -> str:
    """Build a human-readable weather summary from period data."""
    details = period_data.get("instant", {}).get("details", {})
    next_1h = period_data.get("next_1_hours", {})
    next_6h = period_data.get("next_6_hours", {})

    temp = details.get("air_temperature")
    precip = (
        next_1h.get("details", {}).get("precipitation_amount")
        or next_6h.get("details", {}).get("precipitation_amount")
        or 0
    )
    wind = details.get("wind_speed", 0)

    parts = []
    if temp is not None:
        parts.append(f"{temp:.1f}°C")
    if precip > 0:
        parts.append(f"{precip:.1f}mm rain")
    if wind > 0:
        parts.append(f"{wind:.1f}m/s wind")

    return ", ".join(parts) if parts else "No data"


def fetch_weather_forecast(
    latitude: float,
    longitude: float,
    location_name: str | None = None,
) -> WeatherForecast:
    """Fetch weather forecast from Yr.no API.

    Args:
        latitude: Latitude coordinate
        longitude: Longitude coordinate
        location_name: Optional human-readable location name

    Returns:
        WeatherForecast object with periods for the next 7 days

    Raises:
        requests.RequestException: If the API request fails
        ValueError: If the response format is invalid
    """
    logger.debug(
        "Fetching weather forecast from Yr.no",
        extra={"lat": latitude, "lon": longitude, "location": location_name},
    )

    # Yr.no requires a proper User-Agent header
    headers = {
        "User-Agent": f"AI-Chatbot/{Config.APP_VERSION} (contact: {Config.CONTACT_EMAIL})",
    }

    response = requests.get(
        "https://api.met.no/weatherapi/locationforecast/2.0/compact",
        headers=headers,
        params={"lat": latitude, "lon": longitude},
        timeout=Config.WEATHER_API_TIMEOUT,
    )

    if response.status_code >= 400:
        logger.warning(
            "Yr.no API error",
            extra={"status_code": response.status_code, "error": response.text},
        )
        raise requests.RequestException(f"Yr.no API error ({response.status_code})")

    data = response.json()
    properties = data.get("properties", {})
    timeseries = properties.get("timeseries", [])

    if not timeseries:
        raise ValueError("No timeseries data in Yr.no response")

    # Parse forecast periods (limit to next 7 days for planner)
    periods: list[WeatherPeriod] = []
    now = datetime.utcnow()

    for entry in timeseries[:168]:  # 168 hours = 7 days
        time_str = entry.get("time")
        if not time_str:
            continue

        data_entry = entry.get("data", {})
        instant = data_entry.get("instant", {}).get("details", {})
        next_1h = data_entry.get("next_1_hours", {})
        next_6h = data_entry.get("next_6_hours", {})

        # Get symbol code (prefer 1h, fallback to 6h)
        symbol_code = next_1h.get("summary", {}).get("symbol_code") or next_6h.get(
            "summary", {}
        ).get("symbol_code")

        # Get precipitation (prefer 1h, fallback to 6h)
        precipitation = (
            next_1h.get("details", {}).get("precipitation_amount")
            or next_6h.get("details", {}).get("precipitation_amount")
            or 0
        )

        period = WeatherPeriod(
            time=time_str,
            temperature=instant.get("air_temperature", 0),
            precipitation=precipitation,
            wind_speed=instant.get("wind_speed", 0),
            wind_direction=instant.get("wind_from_direction"),
            cloud_coverage=instant.get("cloud_area_fraction"),
            symbol_code=symbol_code,
            summary=_build_summary(data_entry),
        )
        periods.append(period)

    location_str = location_name or f"{latitude},{longitude}"
    logger.info(
        "Weather forecast fetched",
        extra={"location": location_str, "periods": len(periods)},
    )

    return WeatherForecast(
        location=location_str,
        latitude=latitude,
        longitude=longitude,
        periods=periods,
        fetched_at=now.isoformat(),
    )


def get_weather_for_location(
    location: str,
    db: Any = None,
    force_refresh: bool = False,
) -> WeatherForecast | None:
    """Get weather forecast for a location with SQLite caching.

    Args:
        location: Location string in format "City" or "lat,lon"
        db: Database instance for caching (optional)
        force_refresh: Bypass cache and fetch fresh data

    Returns:
        WeatherForecast object or None if location is invalid or API fails
    """
    if not location:
        return None

    # Try to parse as lat,lon coordinates
    try:
        if "," in location:
            parts = location.split(",")
            latitude = float(parts[0].strip())
            longitude = float(parts[1].strip())
            location_name = location
        else:
            # For city names, we need geocoding (not implemented in this version)
            # This would require a separate geocoding service or pre-configured coordinates
            logger.warning(
                "City name geocoding not implemented - use lat,lon coordinates",
                extra={"location": location},
            )
            return None
    except (ValueError, IndexError):
        logger.warning("Invalid location format", extra={"location": location})
        return None

    # Check cache if not forcing refresh
    if not force_refresh and db:
        cached_data = db.get_cached_weather(location)
        if cached_data:
            logger.debug("Returning cached weather", extra={"location": location})
            # Convert dict back to WeatherForecast
            from dataclasses import asdict

            periods = [WeatherPeriod(**p) for p in cached_data.get("periods", [])]
            return WeatherForecast(
                location=cached_data["location"],
                latitude=cached_data["latitude"],
                longitude=cached_data["longitude"],
                periods=periods,
                fetched_at=cached_data["fetched_at"],
            )

    # Fetch fresh data
    try:
        forecast = fetch_weather_forecast(latitude, longitude, location_name)

        # Cache the result if db provided
        if db:
            from dataclasses import asdict

            forecast_dict = asdict(forecast)
            db.cache_weather(location, forecast_dict, ttl_seconds=Config.WEATHER_CACHE_TTL_SECONDS)
            logger.debug("Weather cached", extra={"location": location})

        return forecast

    except (requests.RequestException, ValueError) as e:
        logger.error(
            "Failed to fetch weather forecast",
            extra={"location": location, "error": str(e)},
        )
        return None
