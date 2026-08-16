# Location Awareness — Design Spec

**Date:** 2026-08-16
**Status:** Approved (Approach B — Mapy.com API, no live traffic)

## Goal

Make the agent genuinely useful for location-based tasks — restaurant/POI
suggestions, routes with ETAs, and a location-aware daily briefing — for all
family users, in CZ and abroad, at zero API cost.

Today, location awareness is a single static `USER_LOCATION` env string shared
by all users, plus Yr.no weather for one fixed `WEATHER_LOCATION`. The frontend
never reads device GPS, and the agent has no places/routing data source beyond
`web_search` and the Playwright browser.

## Decisions

- **Provider:** Mapy.com REST API (formerly Mapy.cz) — one API key, free tier
  of 250,000 credits/month, no payment card required. Excellent CZ/SK data;
  OSM-based worldwide coverage abroad. Docs: https://developer.mapy.com/
- **Live traffic:** out of scope. `get_route` ETAs are static. Traffic-aware
  car ETAs via HERE/TomTom free tier is a TODO.md follow-up.
- **Transit:** out of scope for the routing tool (Mapy.com API has no public
  transport). The agent keeps using `web_search`/IDOS for transit questions.
- **Parking/closures:** out of scope.
- **Restaurant ratings:** neither Mapy.com nor OSM provides ratings. System
  prompt guidance tells the agent to follow `search_places` with a
  `web_search` reputation check for restaurant queries.

## 1. Frontend — capturing device location

New `web/src/core/location.ts` wrapping `navigator.geolocation`:

- **Opt-in toggle** "Share device location" in settings. No permission prompt
  on app load — the browser permission dialog triggers only when the user
  enables the toggle. The toggle state lives client-side (localStorage);
  geolocation permission is inherently per-device, so there is no server-side
  setting and no migration.
- **Freshness:** last fix cached in the Zustand store with a timestamp;
  refreshed at message-send time if older than `LOCATION_MAX_AGE_MS`
  (~5 minutes, in `config.ts`).
- **Attachment:** when enabled and a fix is available, coords ride along on
  the chat request. Denied/unavailable permission means the field is simply
  absent — no errors; the agent falls back to saved places.

## 2. Saved places

Per-user named places (home, work, cottage, …) stored in the existing
`kv_store` under a `places` namespace: `name → {address, lat, lon}`. Managed
from the Data page UI (KVStorePage) alongside memories. Respects the
multi-worker constraint (no module state); each user has their own places.

## 3. Backend — request schema + prompt context

- `ChatRequest` gains optional
  `client_location: {lat, lon, accuracy_m, timestamp} | None` with bounds
  validation (lat ∈ [-90, 90], lon ∈ [-180, 180]).
- The static `USER_LOCATION` prompt block becomes dynamic per user:
  - Current locality reverse-geocoded via Mapy.com, cached on rounded coords
    (~3 decimal places) so repeated messages from the same spot don't re-hit
    the API. Include fix age: "near {locality} (device location, {age} min
    old)".
  - The user's saved places (names + addresses).
  - Fallback to the `USER_LOCATION` env var when neither exists.
- **Privacy:** raw coordinates are never persisted — they exist only
  in-flight per request. Reverse-geocoded locality may naturally appear in
  conversation text; that is acceptable.

## 4. Agent tools — `src/agent/tools/places.py`

Gated by `is_places_available()` (presence of `MAPY_CZ_API_KEY`), following
the Garmin/Todoist pattern. Registered in `tools/__init__.py`.

- `search_places(query, near, radius_m)` — POI/geocoding search. `near`
  accepts `"current"` (device coords from request context), a saved place
  name, or a free-text address. Returns name, category, address, distance,
  coords, and a Mapy.com link.
- `get_route(origin, destination, mode)` — car/bike/foot routing. Origin and
  destination accept the same forms as `near`. Returns distance, duration,
  and a Mapy.com link. No traffic (see TODO).

Both are read-only → added to `ALWAYS_SAFE_TOOLS` in
`src/agent/permissions.py` so autonomous agents (briefing) can use them.

Config additions (`src/config.py` + `.env.example` + docs):
`MAPY_CZ_API_KEY`, `MAPY_API_TIMEOUT`.

## 5. Daily briefing

Prompt-only change (per the prompt-only-agents pattern): the briefing prompt
instructs the agent to compute home → first-event travel time via `get_route`
when a home place is saved and the first calendar event has a location, and
include a "leave by" hint. Weather stays on `WEATHER_LOCATION` for now.

## 6. Testing

- **Backend:** unit tests for both tools with mocked Mapy.com responses;
  `ChatRequest` bounds-validation tests; reverse-geocode caching test.
- **Frontend:** unit tests for `location.ts` with mocked
  `navigator.geolocation`; E2E via Playwright `context.setGeolocation`
  verifying toggle → permission → coords-on-request flow, on desktop and
  mobile viewports.
- **Integration:** manual smoke against the real Mapy.com API with the dev
  key before wiring the agent prompt.

## 7. Follow-ups (TODO.md)

- Optional traffic-aware car ETAs: swap `get_route(mode="car")` backend to
  HERE or TomTom free tier; keep Mapy.com for everything else.
