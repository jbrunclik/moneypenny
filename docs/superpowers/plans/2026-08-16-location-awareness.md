# Location Awareness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agent real location capabilities — POI/restaurant search, routing with ETAs, per-user device location and saved places — via the Mapy.com REST API.

**Architecture:** A thin HTTP client (`src/utils/mapy.py`) is shared by two new agent tools (`search_places`, `get_route` in `src/agent/tools/places.py`) and by reverse-geocoding in the prompt context. Device coords arrive as an optional `client_location` field on `ChatRequest`, flow through a new contextvar (same pattern as `set_conversation_context`), and surface in the dynamic user-context prompt. Saved places reuse the existing `kv_store` (namespace `places`) — no new endpoints or UI; the agent manages them via its existing `kv_store` tool, guided by prompt.

**Tech Stack:** Flask + Pydantic (apiflask), `requests`, LangChain `@tool`, Vite/TypeScript frontend, pytest + vitest + Playwright.

**Spec:** `docs/superpowers/specs/2026-08-16-location-awareness-design.md`

## Global Constraints

- Mapy.com REST API base: `https://api.mapy.com/v1`; auth via `X-Mapy-Api-Key` header (never in URL — keeps key out of logs).
- Coordinates are **lon,lat order** in all Mapy API params (`start=14.4378,50.0755`).
- Route types: car → `car_fast_traffic`, bike → `bike_road`, foot → `foot_fast`, hiking → `foot_hiking`.
- Raw device coordinates are never persisted server-side (contextvar only, cleared after each request).
- Env vars `MAPY_CZ_API_KEY`, `MAPY_API_TIMEOUT` (already in `.env.example`).
- Commit directly to `main`, Conventional Commits format.
- Python: type hints everywhere; files < 500 lines; `ruff format` auto-runs via hook.
- The live API key currently returns 403 Forbidden (portal-side restriction, user is fixing). All tests mock HTTP; a live smoke-test step runs whenever the key starts working — do not block on it.

---

### Task 1: Config + Mapy HTTP client

**Files:**
- Modify: `src/config.py` (after the Weather block, ~line 538)
- Create: `src/utils/mapy.py`
- Test: `tests/unit/test_mapy.py`

**Interfaces:**
- Produces: `mapy_geocode(query: str, *, poi_only: bool = False, prefer_near: tuple[float, float] | None = None, limit: int = 8) -> list[dict[str, Any]]`; `mapy_rgeocode(lon: float, lat: float) -> list[dict[str, Any]]`; `mapy_route(start: tuple[float, float], end: tuple[float, float], route_type: str, *, avoid_toll: bool = False) -> dict[str, Any]`; `is_mapy_configured() -> bool`; `MapyError(Exception)`. All coords tuples are `(lon, lat)`.

- [ ] **Step 1: Add config entries**

In `src/config.py`, after `WEATHER_API_TIMEOUT`:

```python
    # Places & Routing (Mapy.com REST API)
    MAPY_CZ_API_KEY: str = os.getenv("MAPY_CZ_API_KEY", "")
    MAPY_API_TIMEOUT: int = int(os.getenv("MAPY_API_TIMEOUT", "10"))  # seconds
```

- [ ] **Step 2: Write failing tests**

`tests/unit/test_mapy.py` — follow the `test_weather.py` style (patch `requests.get`):

```python
"""Tests for the Mapy.com REST API client."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.utils.mapy import MapyError, mapy_geocode, mapy_rgeocode, mapy_route


def _mock_response(status: int, payload: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    return resp


GEOCODE_PAYLOAD = {
    "items": [
        {
            "name": "Kavárna Slavia",
            "label": "Kavárna",
            "position": {"lon": 14.4135, "lat": 50.0813},
            "type": "poi",
            "location": "Praha 1 - Staré Město, Česko",
            "regionalStructure": [
                {"name": "Praha 1", "type": "regional.municipality_part"},
                {"name": "Praha", "type": "regional.municipality"},
                {"name": "Česko", "type": "regional.country", "isoCode": "CZ"},
            ],
        }
    ]
}


@patch("src.utils.mapy.Config")
@patch("src.utils.mapy.requests.get")
def test_geocode_poi_near(mock_get: MagicMock, mock_config: MagicMock) -> None:
    mock_config.MAPY_CZ_API_KEY = "test-key"
    mock_config.MAPY_API_TIMEOUT = 10
    mock_get.return_value = _mock_response(200, GEOCODE_PAYLOAD)

    items = mapy_geocode("kavárna", poi_only=True, prefer_near=(14.42, 50.08), limit=5)

    assert items[0]["name"] == "Kavárna Slavia"
    _, kwargs = mock_get.call_args
    assert kwargs["headers"] == {"X-Mapy-Api-Key": "test-key"}
    assert kwargs["params"]["type"] == "poi"
    assert kwargs["params"]["preferNear"] == "14.42,50.08"
    assert kwargs["params"]["limit"] == 5
    assert "apikey" not in kwargs["params"]


@patch("src.utils.mapy.Config")
@patch("src.utils.mapy.requests.get")
def test_rgeocode(mock_get: MagicMock, mock_config: MagicMock) -> None:
    mock_config.MAPY_CZ_API_KEY = "test-key"
    mock_config.MAPY_API_TIMEOUT = 10
    mock_get.return_value = _mock_response(200, GEOCODE_PAYLOAD)

    items = mapy_rgeocode(14.4378, 50.0755)

    assert items[0]["location"].startswith("Praha 1")
    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {"lon": 14.4378, "lat": 50.0755}


@patch("src.utils.mapy.Config")
@patch("src.utils.mapy.requests.get")
def test_route(mock_get: MagicMock, mock_config: MagicMock) -> None:
    mock_config.MAPY_CZ_API_KEY = "test-key"
    mock_config.MAPY_API_TIMEOUT = 10
    mock_get.return_value = _mock_response(
        200, {"length": 12500, "duration": 1500, "geometry": {}}
    )

    result = mapy_route((14.4009, 50.0711), (14.4378, 50.0755), "car_fast_traffic")

    assert result["length"] == 12500
    assert result["duration"] == 1500
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["start"] == "14.4009,50.0711"
    assert kwargs["params"]["end"] == "14.4378,50.0755"
    assert kwargs["params"]["routeType"] == "car_fast_traffic"


@patch("src.utils.mapy.Config")
@patch("src.utils.mapy.requests.get")
def test_error_raises_mapy_error(mock_get: MagicMock, mock_config: MagicMock) -> None:
    mock_config.MAPY_CZ_API_KEY = "test-key"
    mock_config.MAPY_API_TIMEOUT = 10
    mock_get.return_value = _mock_response(403, {"detail": [{"msg": "Forbidden"}]})

    with pytest.raises(MapyError, match="403"):
        mapy_geocode("Praha")


@patch("src.utils.mapy.Config")
def test_missing_key_raises(mock_config: MagicMock) -> None:
    mock_config.MAPY_CZ_API_KEY = ""
    with pytest.raises(MapyError, match="not configured"):
        mapy_geocode("Praha")
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `.venv/bin/pytest tests/unit/test_mapy.py -v` — expect ImportError/failures.

- [ ] **Step 4: Implement `src/utils/mapy.py`**

```python
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
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `.venv/bin/pytest tests/unit/test_mapy.py -v` — expect PASS.

- [ ] **Step 6: Commit**

```bash
git add src/config.py src/utils/mapy.py tests/unit/test_mapy.py .env.example
git commit -m "feat(location): add Mapy.com REST API client and config"
```

---

### Task 2: `client_location` request field + contextvar plumbing

**Files:**
- Modify: `src/api/schemas.py` (ChatRequest, ~line 165)
- Modify: `src/agent/tools/context.py`
- Modify: `src/api/routes/chat.py` (~lines 191, 310)
- Modify: `src/api/helpers/chat_streaming.py` (~lines 151, 577 `setup_context`, 1102 cleanup)
- Modify: `src/api/helpers/chat_save.py` (~line 97 cleanup)
- Test: `tests/unit/test_schemas_client_location.py`

**Interfaces:**
- Produces: `ClientLocation` Pydantic model (`lat`, `lon`, `accuracy_m`, `timestamp_ms`); `set_location_context(location: dict[str, Any] | None) -> None` and `get_location_context() -> dict[str, Any] | None` in `src/agent/tools/context.py`. The dict shape is `ClientLocation.model_dump()`.

- [ ] **Step 1: Write failing tests**

`tests/unit/test_schemas_client_location.py`:

```python
"""Validation tests for ChatRequest.client_location."""

import pytest
from pydantic import ValidationError

from src.api.schemas import ChatRequest, ClientLocation


def test_chat_request_accepts_client_location() -> None:
    req = ChatRequest(
        message="hi",
        client_location={"lat": 50.0755, "lon": 14.4378, "accuracy_m": 12.5, "timestamp_ms": 1755300000000},
    )
    assert req.client_location is not None
    assert req.client_location.lat == 50.0755


def test_chat_request_client_location_optional() -> None:
    assert ChatRequest(message="hi").client_location is None


@pytest.mark.parametrize("lat,lon", [(91, 0), (-91, 0), (0, 181), (0, -181)])
def test_client_location_bounds(lat: float, lon: float) -> None:
    with pytest.raises(ValidationError):
        ClientLocation(lat=lat, lon=lon)


def test_location_contextvar_roundtrip() -> None:
    from src.agent.tools.context import get_location_context, set_location_context

    assert get_location_context() is None
    set_location_context({"lat": 50.0, "lon": 14.0})
    assert get_location_context() == {"lat": 50.0, "lon": 14.0}
    set_location_context(None)
    assert get_location_context() is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/pytest tests/unit/test_schemas_client_location.py -v`

- [ ] **Step 3: Implement schema + contextvar**

In `src/api/schemas.py`, above `ChatRequest`:

```python
class ClientLocation(BaseModel):
    """Device GPS fix sent by the frontend when location sharing is enabled."""

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0)
    timestamp_ms: int | None = Field(default=None, ge=0)
```

In `ChatRequest`, add field:

```python
    client_location: ClientLocation | None = Field(default=None)
```

In `src/agent/tools/context.py`, following the existing pattern:

```python
# Contextvar holding the device location for the current request (never persisted)
_client_location: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "_client_location", default=None
)


def set_location_context(location: dict[str, Any] | None) -> None:
    """Set the device location for tool/prompt access (ClientLocation.model_dump())."""
    _client_location.set(location)


def get_location_context() -> dict[str, Any] | None:
    """Get the device location for the current request, if shared."""
    return _client_location.get()
```

- [ ] **Step 4: Wire into request lifecycles**

All four sites mirror the existing `set_conversation_context` calls (grep for them; contextvars do NOT cross threads, so the streaming producer-thread re-set in `StreamContext.setup_context` is mandatory):

1. `src/api/routes/chat.py` batch handler (~line 191): after `set_conversation_context(conv_id, user.id)` add
   `set_location_context(data.client_location.model_dump() if data.client_location else None)`;
   in the cleanup block (~line 310) add `set_location_context(None)`.
2. `src/api/routes/chat.py` stream handler (~line 519): pass `data.client_location` into wherever the stream request state is built (follow how `files`/`force_tools` travel into `chat_streaming`).
3. `src/api/helpers/chat_streaming.py`: store `self.client_location: dict[str, Any] | None` on `StreamContext`; in `setup_context()` (runs in the producer thread) call `set_location_context(self.client_location)`; module-level helper at ~line 151 gets the same pair; cleanup site ~line 1102 sets `set_location_context(None)`.
4. `src/api/helpers/chat_save.py` cleanup (~line 97): add `set_location_context(None)`.

- [ ] **Step 5: Run tests + full backend suite**

Run: `.venv/bin/pytest tests/unit/test_schemas_client_location.py -v && make test`
Expected: PASS (streaming tests exercise `setup_context` — if any StreamContext constructor mock breaks, update it; see memory note about updating ALL mocks when signatures change).

- [ ] **Step 6: Commit**

```bash
git add src/api/schemas.py src/agent/tools/context.py src/api/routes/chat.py src/api/helpers/chat_streaming.py src/api/helpers/chat_save.py tests/unit/test_schemas_client_location.py
git commit -m "feat(location): accept client_location on chat requests, expose via contextvar"
```

---

### Task 3: `search_places` + `get_route` agent tools

**Files:**
- Create: `src/agent/tools/places.py`
- Modify: `src/agent/tools/__init__.py` (import + register)
- Modify: `src/agent/permissions.py` (ALWAYS_SAFE_TOOLS)
- Test: `tests/unit/test_places_tools.py`

**Interfaces:**
- Consumes: `mapy_geocode`/`mapy_rgeocode`/`mapy_route`/`is_mapy_configured`/`MapyError` (Task 1); `get_location_context`, `get_conversation_context` (Task 2 / existing).
- Produces: LangChain tools `search_places(query, near="current", limit=5)` and `get_route(origin, destination, mode="car")`, both returning human-readable strings; `is_places_available() -> bool`.

- [ ] **Step 1: Write failing tests**

`tests/unit/test_places_tools.py`:

```python
"""Tests for the places agent tools (search_places, get_route)."""

from unittest.mock import MagicMock, patch

from src.agent.tools.places import get_route, search_places

POI = {
    "name": "Kavárna Slavia",
    "label": "Kavárna",
    "position": {"lon": 14.4135, "lat": 50.0813},
    "type": "poi",
    "location": "Praha 1 - Staré Město, Česko",
    "regionalStructure": [{"name": "Praha", "type": "regional.municipality"}],
}


@patch("src.agent.tools.places.mapy_geocode", return_value=[POI])
@patch("src.agent.tools.places.get_location_context", return_value={"lat": 50.08, "lon": 14.42})
def test_search_places_near_current(mock_loc: MagicMock, mock_geo: MagicMock) -> None:
    result = search_places.invoke({"query": "kavárna", "near": "current"})
    assert "Kavárna Slavia" in result
    assert "km" in result or "m" in result  # distance included
    mock_geo.assert_called_once()
    assert mock_geo.call_args.kwargs["prefer_near"] == (14.42, 50.08)


@patch("src.agent.tools.places.get_location_context", return_value=None)
def test_search_places_current_without_fix(mock_loc: MagicMock) -> None:
    result = search_places.invoke({"query": "kavárna", "near": "current"})
    assert "location" in result.lower()  # graceful message, no crash


@patch("src.agent.tools.places.mapy_geocode", return_value=[POI])
@patch("src.agent.tools.places._get_saved_place", return_value=None)
@patch("src.agent.tools.places.get_location_context", return_value=None)
def test_search_places_near_address(
    mock_loc: MagicMock, mock_saved: MagicMock, mock_geo: MagicMock
) -> None:
    result = search_places.invoke({"query": "lékárna", "near": "Brno"})
    assert "Kavárna Slavia" in result
    # first geocode call resolves "Brno", second searches near it
    assert mock_geo.call_count == 2


@patch("src.agent.tools.places.mapy_route", return_value={"length": 12500, "duration": 1500})
@patch(
    "src.agent.tools.places._get_saved_place",
    side_effect=lambda name: {"lon": 14.40, "lat": 50.07} if name == "home" else None,
)
@patch("src.agent.tools.places.mapy_geocode", return_value=[POI])
def test_get_route_home_to_poi(
    mock_geo: MagicMock, mock_saved: MagicMock, mock_route: MagicMock
) -> None:
    result = get_route.invoke({"origin": "home", "destination": "Kavárna Slavia", "mode": "car"})
    assert "12.5 km" in result
    assert "25 min" in result
    assert mock_route.call_args.args[2] == "car_fast_traffic" or mock_route.call_args.kwargs.get("route_type") == "car_fast_traffic"


@patch("src.agent.tools.places.mapy_route", return_value={"length": 900, "duration": 700})
@patch("src.agent.tools.places._get_saved_place", return_value=None)
@patch("src.agent.tools.places.mapy_geocode", return_value=[POI])
def test_get_route_foot_mode(
    mock_geo: MagicMock, mock_saved: MagicMock, mock_route: MagicMock
) -> None:
    result = get_route.invoke({"origin": "Praha 1", "destination": "Praha 2", "mode": "foot"})
    assert "900 m" in result
    call = mock_route.call_args
    route_type = call.kwargs.get("route_type") or call.args[2]
    assert route_type == "foot_fast"
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/pytest tests/unit/test_places_tools.py -v`

- [ ] **Step 3: Implement `src/agent/tools/places.py`**

```python
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
        return data if "lon" in data and "lat" in data else None
    except (json.JSONDecodeError, TypeError):
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
    items = mapy_geocode(ref, limit=1)
    if not items:
        return None
    pos = items[0]["position"]
    return (pos["lon"], pos["lat"]), items[0]["name"]


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
        query: What to search for, e.g. "italská restaurace", "lékárna", "ČerpacÍ stanice"
        near: Where to search: "current" (user's device location), a saved place
            name (e.g. "home"), or a free-text address/city (e.g. "Brno")
        limit: Max results (default 5)

    Returns:
        Numbered list of matches with locality, distance, and a map link.
        Note: results have no ratings — verify restaurant reputation with web_search.
    """
    try:
        anchor = _resolve_point(near)
        if anchor is None:
            if near.strip().lower() == "current":
                return (
                    "Device location is not available (user hasn't shared it). "
                    "Ask for a neighborhood/city, or use a saved place."
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
            link = f"https://mapy.com/fnc/v1/showmap?center={pos['lon']},{pos['lat']}&zoom=17&marker=true"
            label = item.get("label", "")
            location = item.get("location", "")
            lines.append(f"{i}. {item['name']} ({label}) — {location} — {dist} away — {link}")
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
            f"Route {start_label} → {end_label} ({mode}): "
            f"{_fmt_distance(result['length'])}, ~{_fmt_duration(result['duration'])}. {link}"
        )
    except MapyError as e:
        logger.warning("get_route failed", extra={"error": str(e)})
        return f"Route planning failed: {e}"
```

- [ ] **Step 4: Register the tools**

In `src/agent/tools/__init__.py`:
- Add `from src.agent.tools.places import get_route, is_places_available, search_places`.
- In `get_available_tools()`, after the browser block:

```python
    # Places & routing (Mapy.com) — only when the API key is configured
    if is_places_available():
        tools.append(search_places)
        tools.append(get_route)
```

In `src/agent/permissions.py`, add to `ALWAYS_SAFE_TOOLS` (both are read-only):

```python
    "search_places",
    "get_route",
```

- [ ] **Step 5: Run tests + suite**

Run: `.venv/bin/pytest tests/unit/test_places_tools.py tests/unit/test_agent_tool_modules.py -v && make test`
(`test_agent_tool_modules.py` may enumerate tools — update its expected list if it asserts tool names.)

- [ ] **Step 6: Commit**

```bash
git add src/agent/tools/places.py src/agent/tools/__init__.py src/agent/permissions.py tests/unit/test_places_tools.py
git commit -m "feat(location): add search_places and get_route agent tools (Mapy.com)"
```

---

### Task 4: Dynamic location prompt context + tool guidance

**Files:**
- Modify: `src/agent/prompts.py` (`get_user_context` ~line 1169; static tool-guidance section near the web_search guidance)
- Test: `tests/unit/test_location_prompt_context.py`

**Interfaces:**
- Consumes: `get_location_context` (Task 2), `mapy_rgeocode` (Task 1), `db.kv_list(user_id, "places")` (existing).
- Produces: location section inside `get_user_context()` output; module-private `_reverse_geocode_locality(lon: float, lat: float) -> str | None` with `functools.lru_cache` on coords rounded to 3 decimals (~110 m — stable prompt across messages from the same spot; per-worker cache is fine because it's a pure coords→name function, not user state).

- [ ] **Step 1: Write failing tests**

`tests/unit/test_location_prompt_context.py`:

```python
"""Tests for the dynamic location section of the user context prompt."""

from unittest.mock import MagicMock, patch

from src.agent.prompts import get_user_context


@patch("src.agent.prompts._get_saved_places_lines", return_value=[])
@patch("src.agent.prompts._reverse_geocode_locality", return_value="Praha 1 - Staré Město, Česko")
@patch("src.agent.prompts.get_location_context")
def test_device_location_in_context(
    mock_loc: MagicMock, mock_rgeo: MagicMock, mock_places: MagicMock
) -> None:
    mock_loc.return_value = {"lat": 50.0813, "lon": 14.4135, "accuracy_m": 10, "timestamp_ms": None}
    ctx = get_user_context(user_name="Jiri", user_id="u1")
    assert "Praha 1 - Staré Město" in ctx
    assert "device location" in ctx.lower()


@patch("src.agent.prompts._get_saved_places_lines", return_value=['- home: Nádražní 12, Praha'])
@patch("src.agent.prompts.get_location_context", return_value=None)
def test_saved_places_listed_without_fix(mock_loc: MagicMock, mock_places: MagicMock) -> None:
    ctx = get_user_context(user_name="Jiri", user_id="u1")
    assert "home: Nádražní 12" in ctx


@patch("src.agent.prompts._get_saved_places_lines", return_value=[])
@patch("src.agent.prompts.get_location_context", return_value=None)
def test_env_fallback_when_nothing_shared(mock_loc: MagicMock, mock_places: MagicMock) -> None:
    with patch("src.agent.prompts.Config") as mock_config:
        mock_config.USER_LOCATION = "Prague, Czech Republic"
        ctx = get_user_context(user_name="Jiri", user_id="u1")
    assert "Prague, Czech Republic" in ctx
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/pytest tests/unit/test_location_prompt_context.py -v`

- [ ] **Step 3: Implement in `src/agent/prompts.py`**

Add near the top-level helpers (imports: `functools`, `get_location_context` from `src.agent.tools.context`, `mapy_rgeocode`/`is_mapy_configured`/`MapyError` from `src.utils.mapy`):

```python
@functools.lru_cache(maxsize=256)
def _cached_locality(lon_r: float, lat_r: float) -> str | None:
    """Reverse geocode rounded coords → short locality label (cached per worker)."""
    try:
        items = mapy_rgeocode(lon_r, lat_r)
    except MapyError as e:
        logger.warning("Reverse geocode failed", extra={"error": str(e)})
        return None
    if not items:
        return None
    return items[0].get("location") or items[0].get("name")


def _reverse_geocode_locality(lon: float, lat: float) -> str | None:
    """Locality label for coords, rounded to ~110 m so the cache and prompt stay stable."""
    if not is_mapy_configured():
        return None
    return _cached_locality(round(lon, 3), round(lat, 3))


def _get_saved_places_lines(user_id: str | None) -> list[str]:
    """Bullet lines for the user's saved places (kv_store namespace 'places')."""
    if not user_id:
        return []
    from src.db.models import db

    lines: list[str] = []
    for key, value in db.kv_list(user_id, "places"):
        try:
            data = json.loads(value)
            address = data.get("address", "")
        except (json.JSONDecodeError, TypeError, AttributeError):
            address = ""
        lines.append(f"- {key}: {address}" if address else f"- {key}")
    return lines
```

(Check `db.kv_list`'s actual return shape in `src/db/models/kv_store.py:97` first and adapt the loop — it may return dicts or tuples.)

Replace the static `Config.USER_LOCATION` block inside `get_user_context` with:

```python
    # Location context: device fix > saved places > static env fallback
    location_lines: list[str] = []
    device_loc = get_location_context()
    if device_loc:
        locality = _reverse_geocode_locality(device_loc["lon"], device_loc["lat"])
        if locality:
            location_lines.append(
                f"The user is currently near {locality} (live device location). "
                "Use it for 'near me' requests, local recommendations, and as the "
                "default origin for routes."
            )
    saved_lines = _get_saved_places_lines(user_id)
    if saved_lines:
        location_lines.append(
            "Saved places (usable by name in search_places/get_route):\n" + "\n".join(saved_lines)
        )
    if not location_lines and Config.USER_LOCATION:
        location_lines.append(f"The user is located in {Config.USER_LOCATION}.")
    if location_lines:
        location_lines.append(
            "Use the location for measurement units, local currency, locally "
            "available services, local regulations/holidays/customs, and "
            "date/time formats."
        )
        context_parts.append("## Location\n" + "\n\n".join(location_lines))
```

- [ ] **Step 4: Add static tool guidance**

In the static system prompt's tool-guidance area of `src/agent/prompts.py` (near the web_search guidance — grep for `web_search` in the TOOLS section), add:

```
- **search_places / get_route**: Use for "near me" queries, place lookups, and travel
  times. `near`/`origin`/`destination` accept "current" (device location), a saved
  place name, or an address. Mapy.com data has NO ratings — for restaurant or venue
  quality, follow up with web_search on the top candidates before recommending.
  Car routes use live traffic.
- **Saved places**: When the user shares a home/work/other address worth remembering,
  first resolve coordinates with search_places, then store it with the kv_store tool:
  namespace "places", key = lowercase name (e.g. "home"), value = JSON
  {"address": "...", "lon": ..., "lat": ...}. Users can see these on the Data page.
```

- [ ] **Step 5: Run tests + suite**

Run: `.venv/bin/pytest tests/unit/test_location_prompt_context.py -v && make test`

- [ ] **Step 6: Commit**

```bash
git add src/agent/prompts.py tests/unit/test_location_prompt_context.py
git commit -m "feat(location): per-user dynamic location prompt context + tool guidance"
```

---

### Task 5: Briefing leave-by hint

**Files:**
- Modify: `src/agent/daily_briefing.py` (`BRIEFING_SYSTEM_PROMPT`, line 39)
- Test: `tests/unit/test_daily_briefing.py` (existing file — add one assertion test; if it doesn't exist, create it)

**Interfaces:**
- Consumes: `get_route` tool availability for autonomous agents (Task 3's ALWAYS_SAFE_TOOLS entry).

- [ ] **Step 1: Write failing test**

```python
def test_briefing_prompt_mentions_leave_by_routing() -> None:
    from src.agent.daily_briefing import BRIEFING_SYSTEM_PROMPT

    assert "get_route" in BRIEFING_SYSTEM_PROMPT
    assert "leave by" in BRIEFING_SYSTEM_PROMPT.lower()
```

- [ ] **Step 2: Run test, verify it fails**

- [ ] **Step 3: Extend `BRIEFING_SYSTEM_PROMPT`**

Add numbered step 5 after the kv_store sports step:

```
5. If the get_route tool is available AND the first calendar event has a
   physical location: read the user's home from the kv_store tool
   (namespace "places", key "home"); when home exists, call
   get_route(origin="home", destination=<event location>, mode="car")
   and include a "leave by HH:MM" hint (event start minus route duration,
   minus a 10-minute buffer). Skip silently when there is no home place,
   no located event, or the tool is unavailable.
```

- [ ] **Step 4: Run test + suite, verify pass**

- [ ] **Step 5: Commit**

```bash
git add src/agent/daily_briefing.py tests/unit/test_daily_briefing.py
git commit -m "feat(location): leave-by hint in daily briefing via get_route"
```

---

### Task 6: Frontend — location capture + settings toggle + request wiring

**Files:**
- Create: `web/src/core/location.ts`
- Modify: `web/src/config.ts` (add `LOCATION_MAX_AGE_MS`, `LOCATION_FIX_TIMEOUT_MS`)
- Modify: `web/src/api/client.ts` (`chat.sendBatch` ~line 312, `chat.stream` ~line 346)
- Modify: `web/src/core/messaging.ts` (`sendMessage` ~line 222 — fetch fix, pass through)
- Modify: `web/src/components/SettingsPopup.ts` (toggle row + handler; follow the briefing toggle pattern ~line 661)
- Modify: `web/src/types/api.ts` if a hand-written ChatRequest type exists (check; generated types come from `make types`)
- Test: `web/tests/unit/location.test.ts`

**Interfaces:**
- Produces:
  - `isLocationSharingEnabled(): boolean` / `setLocationSharingEnabled(enabled: boolean): void` (localStorage key `location_sharing_enabled`)
  - `getClientLocation(): Promise<ClientLocation | null>` — returns cached fix if fresher than `LOCATION_MAX_AGE_MS`, otherwise requests a new one with `LOCATION_FIX_TIMEOUT_MS` timeout; resolves `null` when disabled, denied, or timed out (never rejects).
  - `interface ClientLocation { lat: number; lon: number; accuracy_m: number | null; timestamp_ms: number }`

- [ ] **Step 1: Write failing tests**

`web/tests/unit/location.test.ts` (vitest; mock `navigator.geolocation` and `localStorage` per existing unit-test setup):

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getClientLocation,
  isLocationSharingEnabled,
  setLocationSharingEnabled,
  __resetLocationCacheForTests,
} from '../../src/core/location';

function mockGeolocation(impl: (success: PositionCallback, error?: PositionErrorCallback) => void) {
  vi.stubGlobal('navigator', {
    geolocation: { getCurrentPosition: vi.fn(impl) },
  });
}

describe('location', () => {
  beforeEach(() => {
    localStorage.clear();
    __resetLocationCacheForTests();
  });
  afterEach(() => vi.unstubAllGlobals());

  it('is disabled by default', () => {
    expect(isLocationSharingEnabled()).toBe(false);
  });

  it('returns null when sharing is disabled', async () => {
    expect(await getClientLocation()).toBeNull();
  });

  it('returns a fix when enabled and permission granted', async () => {
    setLocationSharingEnabled(true);
    mockGeolocation((success) =>
      success({
        coords: { latitude: 50.08, longitude: 14.42, accuracy: 15 },
        timestamp: 1755300000000,
      } as GeolocationPosition)
    );
    const fix = await getClientLocation();
    expect(fix).toEqual({ lat: 50.08, lon: 14.42, accuracy_m: 15, timestamp_ms: 1755300000000 });
  });

  it('returns cached fix without re-querying when fresh', async () => {
    setLocationSharingEnabled(true);
    const getPos = vi.fn((success: PositionCallback) =>
      success({
        coords: { latitude: 50.08, longitude: 14.42, accuracy: 15 },
        timestamp: Date.now(),
      } as GeolocationPosition)
    );
    vi.stubGlobal('navigator', { geolocation: { getCurrentPosition: getPos } });
    await getClientLocation();
    await getClientLocation();
    expect(getPos).toHaveBeenCalledTimes(1);
  });

  it('resolves null on permission denial', async () => {
    setLocationSharingEnabled(true);
    mockGeolocation((_s, error) =>
      error?.({ code: 1, message: 'denied' } as GeolocationPositionError)
    );
    expect(await getClientLocation()).toBeNull();
  });
});
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd web && npx vitest run tests/unit/location.test.ts`

- [ ] **Step 3: Implement `web/src/core/location.ts`**

```typescript
/**
 * Device location capture for location-aware chat.
 *
 * Opt-in per device (localStorage): the browser permission prompt fires
 * only when the user enables the settings toggle. Fixes are cached and
 * refreshed at message-send time when older than LOCATION_MAX_AGE_MS.
 * Raw coordinates are sent per-request and never persisted server-side.
 */
import { LOCATION_FIX_TIMEOUT_MS, LOCATION_MAX_AGE_MS } from '../config';
import { createLogger } from '../utils/logger';

const log = createLogger('location');
const STORAGE_KEY = 'location_sharing_enabled';

export interface ClientLocation {
  lat: number;
  lon: number;
  accuracy_m: number | null;
  timestamp_ms: number;
}

let cachedFix: ClientLocation | null = null;

export function isLocationSharingEnabled(): boolean {
  return localStorage.getItem(STORAGE_KEY) === 'true';
}

export function setLocationSharingEnabled(enabled: boolean): void {
  localStorage.setItem(STORAGE_KEY, String(enabled));
  if (!enabled) cachedFix = null;
}

/** Get the device location, or null (disabled / denied / unavailable / timeout). */
export async function getClientLocation(): Promise<ClientLocation | null> {
  if (!isLocationSharingEnabled()) return null;
  if (!('geolocation' in (navigator ?? {}))) return null;
  if (cachedFix && Date.now() - cachedFix.timestamp_ms < LOCATION_MAX_AGE_MS) {
    return cachedFix;
  }
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        cachedFix = {
          lat: pos.coords.latitude,
          lon: pos.coords.longitude,
          accuracy_m: pos.coords.accuracy ?? null,
          timestamp_ms: pos.timestamp,
        };
        resolve(cachedFix);
      },
      (err) => {
        log.debug('Geolocation unavailable', { code: err.code });
        resolve(null);
      },
      { timeout: LOCATION_FIX_TIMEOUT_MS, maximumAge: LOCATION_MAX_AGE_MS }
    );
  });
}

/** Test-only: clear the module-level fix cache. */
export function __resetLocationCacheForTests(): void {
  cachedFix = null;
}
```

`web/src/config.ts` additions:

```typescript
/** Reuse a device location fix younger than this at message-send time. */
export const LOCATION_MAX_AGE_MS = 5 * 60 * 1000;
/** Give up waiting for a GPS fix after this long (send without location). */
export const LOCATION_FIX_TIMEOUT_MS = 3000;
```

- [ ] **Step 4: Run tests, verify they pass**

- [ ] **Step 5: Wire into requests**

- `web/src/api/client.ts`: add optional `clientLocation?: ClientLocation | null` parameter to `chat.sendBatch` and `chat.stream`; include `client_location: clientLocation ?? undefined` in both JSON bodies (next to `anonymous_mode`).
- `web/src/core/messaging.ts` `sendMessage()`: before issuing the request, `const clientLocation = await getClientLocation();` and pass it through to the client call(s). Also pass it in the retry/resume path if it re-issues the original request (grep for `chat.stream(` call sites in messaging.ts).
- Regenerate types: `make openapi && make types` (updates `web/src/types/generated-api.ts` with `client_location`).

- [ ] **Step 6: Settings toggle**

In `web/src/components/SettingsPopup.ts`, add a "Location" section following the Daily Briefing toggle markup (~line 661):

```typescript
// In the settings HTML template:
<div class="settings-section">
  <h3>Location</h3>
  <label class="toggle-label">
    <input type="checkbox" id="location-sharing-enabled" ${isLocationSharingEnabled() ? 'checked' : ''}>
    <span class="toggle-switch"></span>
    <span class="toggle-text">Share device location with the assistant</span>
  </label>
  <p class="settings-hint">Used for "near me" suggestions and routes. Sent only with your messages, never stored. This device only.</p>
</div>
```

Change handler (event delegation, same block as the briefing checkbox):

```typescript
if (target.id === 'location-sharing-enabled') {
  const enabled = (target as HTMLInputElement).checked;
  setLocationSharingEnabled(enabled);
  if (enabled) {
    // Trigger the browser permission prompt immediately so denial is visible now
    void getClientLocation().then((fix) => {
      if (!fix) showToast('Location permission denied or unavailable', 'error');
    });
  }
}
```

(Use the actual toast helper name found in SettingsPopup.ts — grep `Toast` import.)

- [ ] **Step 7: Run full frontend checks**

Run: `cd web && npx vitest run && npx eslint src tests && npx tsc --noEmit`
Expected: PASS. **Test on both desktop and mobile viewports** (CLAUDE.md rule) — the settings section must render correctly at < 768px.

- [ ] **Step 8: Commit**

```bash
git add web/src/core/location.ts web/src/config.ts web/src/api/client.ts web/src/core/messaging.ts web/src/components/SettingsPopup.ts web/src/types/ web/tests/unit/location.test.ts
git commit -m "feat(location): device location capture, settings toggle, request wiring"
```

---

### Task 7: E2E test

**Files:**
- Create: `web/tests/e2e/location.spec.ts` (follow the structure of an existing settings-related E2E spec; reuse the mock server + auth fixtures)

**Interfaces:**
- Consumes: settings toggle id `location-sharing-enabled` (Task 6), request body field `client_location` (Task 2/6).

- [ ] **Step 1: Write the E2E test**

```typescript
import { expect, test } from './fixtures';  // adapt to the project's fixture import

test.use({
  geolocation: { latitude: 50.0813, longitude: 14.4135 },
  permissions: ['geolocation'],
});

test('sends client_location with chat when sharing is enabled', async ({ page }) => {
  // (setup/login per existing fixtures)
  await page.goto('/');

  // Enable the toggle in Settings
  await page.getByRole('button', { name: /settings/i }).click();
  await page.locator('#location-sharing-enabled').check();
  await page.keyboard.press('Escape');

  // Capture the chat request body
  const requestPromise = page.waitForRequest((req) =>
    req.url().includes('/chat/stream') && req.method() === 'POST'
  );
  await page.getByRole('textbox').fill('what is near me?');
  await page.keyboard.press('Enter');

  const request = await requestPromise;
  const body = request.postDataJSON() as { client_location?: { lat: number; lon: number } };
  expect(body.client_location?.lat).toBeCloseTo(50.0813, 3);
  expect(body.client_location?.lon).toBeCloseTo(14.4135, 3);
});

test('omits client_location when sharing is disabled', async ({ page }) => {
  await page.goto('/');
  const requestPromise = page.waitForRequest((req) =>
    req.url().includes('/chat/stream') && req.method() === 'POST'
  );
  await page.getByRole('textbox').fill('hello');
  await page.keyboard.press('Enter');
  const body = (await requestPromise).postDataJSON() as Record<string, unknown>;
  expect(body.client_location).toBeUndefined();
});
```

Adapt selectors/fixtures to the real E2E infra (read 2-3 existing specs first; the mock-server pattern is documented in the e2e-debugger agent's knowledge and `web/tests/e2e/`).

- [ ] **Step 2: Run E2E suite with timeout**

Run: `cd web && timeout 600 npx playwright test tests/e2e/location.spec.ts`
Expected: PASS on desktop + mobile projects. Zero tolerance for flakiness — poll, don't sleep.

- [ ] **Step 3: Commit**

```bash
git add web/tests/e2e/location.spec.ts
git commit -m "test(e2e): location sharing toggle sends client_location with chat"
```

---

### Task 8: Live smoke test + docs

**Files:**
- Create: `docs/features/location.md`
- Modify: `docs/README.md` (index entry), `CLAUDE.md` (tools list line: add places/routing to the agent tools enumeration)

- [ ] **Step 1: Live smoke test (when the API key works)**

```bash
KEY=$(grep "^MAPY_CZ_API_KEY=" .env | cut -d= -f2)
curl -s -H "X-Mapy-Api-Key: $KEY" "https://api.mapy.com/v1/geocode?query=kav%C3%A1rna&type=poi&preferNear=14.42,50.08&limit=3&lang=cs"
curl -s -H "X-Mapy-Api-Key: $KEY" "https://api.mapy.com/v1/rgeocode?lon=14.4378&lat=50.0755"
curl -s -H "X-Mapy-Api-Key: $KEY" "https://api.mapy.com/v1/routing/route?start=14.4009,50.0711&end=16.6068,49.1951&routeType=car_fast_traffic&format=polyline" | head -c 400
```

Verify the mock payload shapes in `tests/unit/test_mapy.py` match reality (`items[].position.{lon,lat}`, `length`/`duration`); fix mocks if they diverge. If the key still returns 403: report to the user, do not block the remaining steps.

- [ ] **Step 2: Write `docs/features/location.md`**

Cover: architecture (client → contextvar → tools/prompt), the `places` kv namespace format, env vars, the no-ratings caveat + web_search follow-up pattern, privacy model (coords in-flight only, per-device opt-in), briefing leave-by behavior, and the TODO (traffic provider alternatives). Link the spec. Add the index line to `docs/README.md` and update the CLAUDE.md tools enumeration (`web_search, fetch_url, browser, generate_image, execute_code, todoist, etc.` → mention places/routing).

- [ ] **Step 3: Full pre-commit verification**

Run: `make lint && make test-all`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add docs/features/location.md docs/README.md CLAUDE.md
git commit -m "docs(location): feature docs for places, routing, and device location"
```
