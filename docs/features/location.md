# Location Awareness

Places search, routing, and device-location context for the agent, backed by
the Mapy.com REST API. Spec:
[2026-08-16-location-awareness-design.md](../superpowers/specs/2026-08-16-location-awareness-design.md).

## Architecture

```
Frontend                          Backend
--------                          -------
Settings toggle (per device)      ChatRequest.client_location (Pydantic, bounds-checked)
  └─ localStorage                    └─ set_location_context() contextvar
core/location.ts                        ├─ re-set in the stream producer thread
  └─ navigator.geolocation              │  (contextvars don't cross threads)
     cached fix, refreshed when         ├─ prompts.get_user_context(): "near {locality}"
     older than LOCATION_MAX_AGE_MS     │  via cached reverse geocode
     at message-send time               └─ tools/places.py: near="current"
```

- **HTTP client**: [src/utils/mapy.py](../../src/utils/mapy.py) — geocode,
  rgeocode, routing. Auth via `X-Mapy-Api-Key` header (keeps the key out of
  URL logs). Coordinates are always **(lon, lat)** tuples, matching Mapy API
  order.
- **Agent tools**: [src/agent/tools/places.py](../../src/agent/tools/places.py)
  — `search_places(query, near, limit)` and
  `get_route(origin, destination, mode)`. Registered only when
  `MAPY_CZ_API_KEY` is configured; both are in `ALWAYS_SAFE_TOOLS`
  (read-only), so autonomous agents (e.g. Daily Briefing) can call them.
- **Location resolution order** (for `near`/`origin`/`destination`):
  `"current"` (device fix from contextvar) → saved place (kv_store) →
  free-text geocode.
- **Route modes**: car → `car_fast_traffic` (live traffic in CZ), bike →
  `bike_road`, foot → `foot_fast`, hiking → `foot_hiking`. No public
  transport in the Mapy API — the agent uses web_search/IDOS for that.

## Saved places

Stored in the existing kv_store, namespace `places`:
key = lowercase name (e.g. `home`), value = JSON
`{"address": "...", "lon": <number>, "lat": <number>}`.

There is no dedicated UI — the agent has full CRUD via dedicated tools:
`save_place(name, address)` (create/update — geocodes and stores),
`list_places()`, `delete_place(name)`, guided by `TOOLS_SYSTEM_PROMPT_PLACES`
in [prompts.py](../../src/agent/prompts.py). Users can also view/delete
entries on the Data page. Saved place names work directly in
search_places/get_route and are listed in the user-context prompt.

Note: the generic `kv_store` tool is bound only in sports/language/agent
conversations — regular chats cannot use it, which is why the dedicated
places tools exist. `save_place`/`delete_place` are excluded in anonymous
mode (they write persistent user data, like `manage_memory`) and are NOT in
`ALWAYS_SAFE_TOOLS` (autonomous agents need an explicit permission grant to
modify places; read-only `search_places`/`get_route`/`list_places` need
none). All five places tools are in `_TOOL_MAP`, so permission-restricted
agents can be granted them.

## Prompt context

`get_user_context()` builds the `## Location` section per request:
1. Device fix → reverse-geocoded locality ("The user is currently near
   Praha 2 - Vinohrady…"). Cached per worker via `lru_cache` on coords
   rounded to 3 decimals (~110 m) so repeated messages from the same spot
   don't re-hit the API and keep the prompt stable.
2. Saved places list.
3. Fallback: the static `USER_LOCATION` env var (pre-existing behavior).

Tool docs live in `TOOLS_SYSTEM_PROMPT_PLACES`, included only when the key
is configured (env-stable, so the cached static prompt prefix stays stable).

## Privacy model

- Sharing is **opt-in per device** (localStorage toggle in Settings); the
  browser permission prompt fires when the toggle is enabled, not on load.
- Raw coordinates travel only in-flight on chat requests and live in a
  request-scoped contextvar — they are **never persisted** server-side.
- The reverse-geocoded locality may naturally appear in conversation text.

## Ratings caveat

Mapy.com data has **no ratings/reviews**. The system prompt instructs the
agent to follow `search_places` with a `web_search` reputation check for
restaurant/venue quality questions.

## Daily briefing

The briefing prompt (prompt-only change in
[daily_briefing.py](../../src/agent/daily_briefing.py)) computes a
home → first-event travel time via `get_route` and includes a
"leave by HH:MM" hint (event start − duration − 10 min buffer) when a
`home` place is saved and the event has a location.

## Configuration

| Env var | Default | Meaning |
|---------|---------|---------|
| `MAPY_CZ_API_KEY` | `""` | Mapy.com REST API key; empty disables the tools |
| `MAPY_API_TIMEOUT` | `10` | Request timeout (seconds) |

Get a key at https://developer.mapy.com/account/ (Seznam login, free tier
250k credits/month, no card). Restrict the key to geocoding + reverse
geocoding + routing in the portal.

## Pitfalls

- **Permissions-Policy**: `geolocation=(self)` in
  [app.py](../../src/app.py) security headers is required — with the
  previous `geolocation=()`, Chromium (desktop + Android) silently blocks
  `navigator.geolocation` while WebKit does not, which made the bug
  browser-specific. Caught by the location E2E tests.
- **E2E serves the production build**: the Playwright web server
  (`tests/e2e-server.py`) serves `static/assets` — run `make build` before
  E2E when frontend code changed, and kill any reused server on port 8001
  (`reuseExistingServer: !CI`) after a rebuild.
- The chat endpoints' request bodies are NOT in the OpenAPI spec
  (`@validate_request` is a custom decorator), so `client_location` types
  are hand-written in [types/api.ts](../../web/src/types/api.ts), matching
  the existing pattern for `force_tools`/`anonymous_mode`.

## Follow-ups

- Traffic-aware ETAs outside CZ (HERE/TomTom free tier) — tracked in
  TODO.md. Note `car_fast_traffic` already uses live traffic where Mapy.com
  has coverage (CZ/SK).
