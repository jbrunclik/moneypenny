"""Thin client for the Mapy.com REST API (geocoding, reverse geocoding, routing).

Used by the places agent tools and by prompt-context reverse geocoding.
Coordinates are always (lon, lat) tuples, matching the Mapy API order.
Docs: https://developer.mapy.com/rest-api-mapy-cz/
"""

from typing import Any

import requests

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

MAPY_BASE_URL = "https://api.mapy.com/v1"


class MapyError(Exception):
    """Raised when the Mapy.com API is unavailable, misconfigured, or errors."""


def is_mapy_configured() -> bool:
    """Whether the Mapy.com API key is set."""
    return bool(Config.MAPY_CZ_API_KEY)


def _get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """Issue an authenticated GET; raise MapyError on any failure."""
    if not Config.MAPY_CZ_API_KEY:
        raise MapyError("Mapy.com API is not configured (MAPY_CZ_API_KEY missing)")
    try:
        response = requests.get(
            f"{MAPY_BASE_URL}/{path}",
            params=params,
            headers={"X-Mapy-Api-Key": Config.MAPY_CZ_API_KEY},
            timeout=Config.MAPY_API_TIMEOUT,
        )
    except requests.RequestException as e:
        raise MapyError(f"Mapy.com API request failed: {e}") from e
    if response.status_code != 200:
        raise MapyError(f"Mapy.com API returned {response.status_code} for /{path}")
    return response.json()  # type: ignore[no-any-return]


def mapy_geocode(
    query: str,
    *,
    poi_only: bool = False,
    prefer_near: tuple[float, float] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Search places/addresses. prefer_near biases results to (lon, lat)."""
    params: dict[str, Any] = {"query": query, "limit": limit, "lang": "cs"}
    if poi_only:
        params["type"] = "poi"
    if prefer_near is not None:
        params["preferNear"] = f"{prefer_near[0]},{prefer_near[1]}"
    return _get("geocode", params).get("items", [])


def mapy_rgeocode(lon: float, lat: float) -> list[dict[str, Any]]:
    """Reverse geocode coordinates to regional entities (smallest first)."""
    return _get("rgeocode", {"lon": lon, "lat": lat}).get("items", [])


def mapy_route(
    start: tuple[float, float],
    end: tuple[float, float],
    route_type: str,
    *,
    avoid_toll: bool = False,
) -> dict[str, Any]:
    """Plan a route; returns dict with length (m) and duration (s)."""
    params: dict[str, Any] = {
        "start": f"{start[0]},{start[1]}",
        "end": f"{end[0]},{end[1]}",
        "routeType": route_type,
        "format": "polyline",
    }
    if avoid_toll:
        params["avoidToll"] = "true"
    return _get("routing/route", params)
