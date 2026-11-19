# get_weather Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** an agent tool that returns a Yr.no forecast for any place.
**Architecture:** `src/agent/tools/weather.py` composes `places.resolve_point` (renamed from `_resolve_point`), `utils.weather.get_weather_for_location` and `services.planner.weather.daily_weather`.
**Tech Stack:** LangChain `@tool`, httpx (existing client), pytest.
**Spec:** `docs/superpowers/specs/2026-11-19-weather-tool-design.md`

## Global Constraints
- Signature `get_weather(location: str = "current", days: int = 3) -> str`; days clamped 1-7.
- Failures via `tool_error`; an unresolved place or a missing device fix is `retriable=False` with the same Settings hint as places.
- Coordinates rounded to 2 decimals as the cache key `"lat,lon"`.

## Review Focus
1. "current" with no device fix → a non-retriable error naming the Settings path (`test_current_without_fix`).
2. Yr.no down → `tool_error`, not an exception (`test_forecast_unavailable`).
3. days outside 1-7 → clamped (`test_days_clamped`).
4. Local dates (Europe/Prague), not UTC dates (`test_days_are_local_dates`).
5. The schema stays Gemini-convertible (`TestToolSchema`).

### Task 1: the tool (TDD)
Files: create `src/agent/tools/weather.py`, `tests/unit/test_weather_tool.py`; modify `src/agent/tools/places.py` (rename `_resolve_point` → `resolve_point`).
- [ ] Tests: the five above, plus `test_daily_summary_fields` (a two-day fake forecast → entries with date/low_c/high_c/rain_mm/wind_max_ms/symbol) and `test_hourly_only_when_today_in_range`. Run → FAIL.
- [ ] Implement; run → PASS.

### Task 2: registration (checklist in docs/features/agent-tools.md)
`tools/__init__.py` (bind with places, export), `ALWAYS_SAFE_TOOLS`, `tool_display.py` (metadata + detail = place), `agent_assist.py` `_PROMPT_TOOL_DESCRIPTIONS`, `JobEditor.ts` `BASE_TOOLS`, `make prompt-snapshots`. Run `test_tool_display.py`, `test_prompt_snapshots.py` → PASS.

### Task 3: prompts, evals, docs, announcement
Freshness gate lookup=false gets "weather forecasts (the get_weather tool)"; core prompt's web-tools list drops weather and points at get_weather. Eval cases `weather_tomorrow_city_cs`, `weather_umbrella_current`; run `--only` (report cost). Docs: agent-tools table, location.md section, regular-review check, TODO re-measure, announcement (cs+en).

### Task 4: gate, commit, deploy
`make lint`, `make test-all E2E_PORT=8011` (JobEditor changed), exit codes; commit `feat(agent): get_weather tool on Yr.no forecasts`; push; deploy.
