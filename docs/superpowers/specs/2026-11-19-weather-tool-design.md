# get_weather agent tool - design (short)

**Intent.** Weather questions ("what's the weather in Brno tomorrow", "do I
need an umbrella") are answered today by a web search, often from pages
that are not a forecast. Yr.no (MET Norway) is already wired in
(`src/utils/weather.py`, 6 h cache) for the planner's one location; give the
agent a forecast for any place.

**Goals.**
- `get_weather(location="current", days=3)` in `src/agent/tools/weather.py`.
  `location` resolves like the places tools (`resolve_point` in `places.py`:
  "current" device fix -> saved place -> Mapy.com geocode); `days` clamped to 1-7.
- Result (JSON): place label, source "Yr.no (MET Norway)", `fetched_at`, one
  entry per local day (date, low/high C, rain mm, max wind m/s, symbol), and
  the next 12 hours hourly when today is in range.
- The forecast goes through `get_weather_for_location` with coordinates rounded
  to 2 decimals (shared cache, Yr.no ToS asks for few decimals).
- Bound with the places tools (Mapy.com key configured); read-only, so in
  `ALWAYS_SAFE_TOOLS`.
- The freshness gate's lookup=false list and the core prompt's web-tools list
  stop sending weather to web search.
- A8: "Weather fetched" log line (location kind, cache hit, days); a
  regular-review check; a re-measure ~Dec 3 2026 in TODO.md.
- A7: a What's-new announcement.

**Non-goals.** No new weather provider, no weather alerts, no planner change.

**Approaches.** (1) A dedicated tool on Yr.no (chosen): structured, free, cached,
and it works for agents with no web search. (2) Keep web search and improve
queries: pages are often stale or for the wrong place. (3) A `weather`
action on `search_places`: hides the capability in a tool the model doesn't
associate with weather.

**Left to the builder.** Result field names, test layout, eval wording.
