"""Places and routing tools backed by the Mapy.com REST API.

search_places finds POIs/addresses; get_route plans car/bike/foot routes.
Location references resolve in priority order: "current" (device fix from
the request contextvar) → saved place (kv_store namespace "places") →
free-text geocode.
"""

import json
import math
from typing import Any

from langchain_core.tools import tool

from src.agent.tools.context import get_conversation_context, get_location_context
from src.utils.logging import get_logger
from src.utils.mapy import MapyError, is_mapy_configured, mapy_geocode, mapy_route

logger = get_logger(__name__)

PLACES_KV_NAMESPACE = "places"

_ROUTE_TYPES = {
    "car": "car_fast_traffic",
    "bike": "bike_road",
    "foot": "foot_fast",
    "hiking": "foot_hiking",
}


def is_places_available() -> bool:
    """Places tools are available when the Mapy.com API key is configured."""
    return is_mapy_configured()


def _get_saved_place(name: str) -> dict[str, Any] | None:
    """Look up a saved place by name in the user's kv_store places namespace."""
    _, user_id = get_conversation_context()
    if not user_id:
        return None
    from src.db.models import db

    raw = db.kv_get(user_id, PLACES_KV_NAMESPACE, name.strip().lower())
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, dict) and "lon" in data and "lat" in data:
        return data
    return None


def _resolve_point(ref: str) -> tuple[tuple[float, float], str] | None:
    """Resolve a location reference to ((lon, lat), label) or None."""
    ref = ref.strip()
    if ref.lower() == "current":
        loc = get_location_context()
        if not loc:
            return None
        return (loc["lon"], loc["lat"]), "current location"
    saved = _get_saved_place(ref)
    if saved:
        return (saved["lon"], saved["lat"]), ref
    items = mapy_geocode(ref, limit=3)
    if not items:
        return None
    # Prefer regional entities (cities, streets, addresses) over POIs: the top
    # hit for a plain city name can be a POI (e.g. "Brno" -> Brno dam)
    best = next((i for i in items if str(i.get("type", "")).startswith("regional")), items[0])
    pos = best["position"]
    return (pos["lon"], pos["lat"]), best["name"]


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> int:
    """Haversine distance in meters between (lon, lat) points."""
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return int(2 * 6371000 * math.asin(math.sqrt(h)))


def _fmt_distance(meters: int) -> str:
    return f"{meters / 1000:.1f} km" if meters >= 1000 else f"{meters} m"


def _fmt_duration(seconds: int) -> str:
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"


@tool
def search_places(query: str, near: str = "current", limit: int = 5) -> str:
    """Search for places (restaurants, shops, POIs, addresses) near a location.

    Args:
        query: What to search for, e.g. "italská restaurace", "lékárna", "čerpací stanice"
        near: Where to search: "current" (user's device location), a saved place
            name (e.g. "home"), or a free-text address/city (e.g. "Brno")
        limit: Max results (default 5)

    Returns:
        Numbered list of matches with locality, distance, and a map link.
        Note: results have no ratings - verify restaurant reputation with web_search.
    """
    try:
        anchor = _resolve_point(near)
        if anchor is None:
            if near.strip().lower() == "current":
                return (
                    "Device location is not available - the user has not enabled "
                    "location sharing on this device. Tell them they can enable it "
                    'via Settings -> Location -> "Share device location with the '
                    'assistant" (the browser will then ask for permission once). '
                    "Meanwhile, answer with what you have: ask for a "
                    "neighborhood/city, or use a saved place."
                )
            return f"Could not resolve location '{near}'."
        (anchor_pt, anchor_label) = anchor
        items = mapy_geocode(query, poi_only=True, prefer_near=anchor_pt, limit=limit)
        if not items:
            return f"No places found for '{query}' near {anchor_label}."
        lines = [f"Places matching '{query}' near {anchor_label}:"]
        for i, item in enumerate(items, 1):
            pos = item["position"]
            dist = _fmt_distance(_distance_m(anchor_pt, (pos["lon"], pos["lat"])))
            link = (
                "https://mapy.com/fnc/v1/showmap"
                f"?center={pos['lon']},{pos['lat']}&zoom=17&marker=true"
            )
            label = item.get("label", "")
            location = item.get("location", "")
            lines.append(f"{i}. {item['name']} ({label}) - {location} - {dist} away - {link}")
        return "\n".join(lines)
    except MapyError as e:
        logger.warning("search_places failed", extra={"error": str(e)})
        return f"Places search failed: {e}"


@tool
def get_route(origin: str, destination: str, mode: str = "car") -> str:
    """Plan a route and get distance + ETA between two locations.

    Args:
        origin: Start: "current" (device location), a saved place name, or an address
        destination: End: same formats as origin
        mode: "car" (traffic-aware), "bike", "foot", or "hiking"

    Returns:
        Distance, duration, and a map link for the route.
    """
    route_type = _ROUTE_TYPES.get(mode)
    if route_type is None:
        return f"Unknown mode '{mode}'. Use one of: {', '.join(_ROUTE_TYPES)}."
    try:
        start = _resolve_point(origin)
        if start is None:
            return f"Could not resolve origin '{origin}'."
        end = _resolve_point(destination)
        if end is None:
            return f"Could not resolve destination '{destination}'."
        (start_pt, start_label) = start
        (end_pt, end_label) = end
        result = mapy_route(start_pt, end_pt, route_type)
        link = (
            f"https://mapy.com/fnc/v1/route?start={start_pt[0]},{start_pt[1]}"
            f"&end={end_pt[0]},{end_pt[1]}&routeType={route_type}"
        )
        return (
            f"Route {start_label} -> {end_label} ({mode}): "
            f"{_fmt_distance(result['length'])}, ~{_fmt_duration(result['duration'])}. {link}"
        )
    except MapyError as e:
        logger.warning("get_route failed", extra={"error": str(e)})
        return f"Route planning failed: {e}"
