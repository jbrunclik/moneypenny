# Planner Mode

The Planner is a dedicated productivity space that combines Todoist tasks and Google Calendar events into a unified 7-day dashboard. The LLM acts as an executive strategist, providing proactive analysis and recommendations.

## Overview

1. **Daily Planning Session**: Ephemeral conversation that resets at 4am daily
2. **Dashboard Context**: LLM receives structured JSON of upcoming 7 days with tasks and events
3. **Proactive Analysis**: On first load, LLM analyzes schedule and suggests priorities
4. **Strategic Time-Blocking**: LLM helps allocate focus time and balance commitments

## Planner-Specific Tool: refresh_planner_dashboard

In planner mode, the LLM has access to an additional tool that ensures it always has current information after making changes.

**Purpose**: After modifying tasks (via `todoist` tool) or calendar events (via `google_calendar` tool), the LLM can refresh the dashboard data to see the updated state of the user's schedule.

**When to use**:
- After adding, updating, completing, or deleting tasks
- After creating, updating, or deleting calendar events
- When verifying that changes were applied correctly
- Before providing recommendations based on the current schedule state

**How it works**:
1. Tool fetches fresh data from Todoist and Google Calendar APIs (bypassing cache)
2. Updates the in-memory context variable with the new dashboard state
3. Next time the system prompt is built, it includes the refreshed data
4. Returns a summary of the refreshed data (event count, task count, overdue tasks)

**Implementation details**:
- Only available in planner mode (not in regular conversations)
- Requires at least one integration to be connected (Todoist or Calendar)
- Uses the `_planner_dashboard_context` contextvar (in [agent.py](../../src/agent/agent.py)) to update the dashboard mid-conversation
- System prompt checks contextvar for updated data before using the initial dashboard_data

## Dashboard Data Structure

The dashboard data is injected into the system prompt as JSON with this structure:

**Multi-day event handling**: All-day events spanning multiple days (e.g., Monday-Wednesday conference) appear on every day they occur. Google Calendar's `end_date` is exclusive, so an event with `start_date: 2024-12-23` and `end_date: 2024-12-26` spans Dec 23-25 (3 days). This ensures the LLM and user have complete context about ongoing multi-day events.

```json
{
  "integrations": {
    "todoist_connected": true,
    "calendar_connected": true,
    "todoist_error": null,
    "calendar_error": null
  },
  "overdue_tasks": [
    {
      "content": "Task title",
      "priority": 4,
      "project_name": "Work",
      "due_string": "yesterday",
      "due_date": "2024-12-24",
      "is_recurring": false,
      "labels": ["urgent"]
    }
  ],
  "days": [
    {
      "day_name": "Today",
      "date": "2024-12-25",
      "events": [
        {
          "summary": "Team standup",
          "start": "2024-12-25T10:00:00",
          "end": "2024-12-25T10:30:00",
          "is_all_day": false,
          "location": "Zoom",
          "attendees": [...]
        }
      ],
      "tasks": [
        {
          "content": "Review PR #123",
          "priority": 3,
          "project_name": "Development",
          "section_name": "In Progress",
          "due_date": "2024-12-25",
          "is_recurring": false,
          "labels": ["code-review"]
        }
      ]
    },
    // ... 6 more days
  ]
}
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/planner` | GET | Fetch planner dashboard data (7 days) |
| `/api/planner/conversation` | GET | Get or create planner conversation |
| `/api/planner/reset` | POST | Manually reset planner conversation |
| `/api/planner/sync` | GET | Get planner state for real-time sync |

**Query parameters**:
- `force_refresh=true` - Bypass cache and fetch fresh data (used by refresh button)

## Caching

Dashboard data is cached in SQLite (`dashboard_cache` table, one row per user) with a 5-minute TTL so every gunicorn worker sees the same data:
- Cache row: keyed by `user_id`, with `expires_at` ([models/cache.py](../../src/db/models/cache.py))
- TTL: 5 minutes (configurable via `DASHBOARD_CACHE_TTL_SECONDS`)
- Invalidation: Manual reset or `force_refresh=true` parameter
- Bypass: `refresh_planner_dashboard` tool always fetches fresh data

## Key Files

**Backend:**
- [planner_data.py](../../src/utils/planner_data.py) - Dashboard building logic
- [tools/planner.py](../../src/agent/tools/planner.py) - refresh_planner_dashboard tool
- [routes/planner.py](../../src/api/routes/planner.py) - Planner API endpoints
- [prompt_texts/planner.py](../../src/agent/prompt_texts/planner.py) - `PLANNER_SYSTEM_PROMPT`; [prompt_dashboard.py](../../src/agent/prompt_dashboard.py) - dashboard context injection
- [models/](../../src/db/models/) - Planner conversation management and caching

**Frontend:**
- [PlannerView.ts](../../web/src/components/PlannerView.ts) - Planner container
- [PlannerDashboard.ts](../../web/src/components/PlannerDashboard.ts) - Dashboard rendering
- [planner.css](../../web/src/styles/components/planner.css) - Planner-specific styles
- UI structure, CSS classes and visual patterns: [Planner Dashboard UI](../ui/planner-dashboard.md)

## Testing

- Unit tests: [test_planner.py](../../tests/unit/test_planner.py) - Dashboard building, tool behavior
- E2E tests: [planner.spec.ts](../../web/tests/e2e/planner.spec.ts) - User flows
- Visual tests: [planner.visual.ts](../../web/tests/visual/planner.visual.ts) - Dashboard snapshots
- Coverage details: [Frontend and E2E Testing](../testing/frontend.md#planner-tests), [Backend Testing](../testing/backend.md#planner-tests-backend)

## Weather Integration (Yr.no)

The planner dashboard includes weather forecast data from Yr.no (Norwegian Meteorological Institute) to provide location-aware planning context.

### Overview

Weather data is automatically fetched and included in the planner dashboard when `WEATHER_LOCATION` is configured. The forecast provides 7-day weather summaries with temperature ranges, precipitation, and weather symbols.

### Configuration

```bash
# .env
WEATHER_LOCATION=50.0755,14.4378  # Latitude,longitude for Prague
WEATHER_CACHE_TTL_SECONDS=21600  # 6 hours (weather doesn't change often)
WEATHER_API_TIMEOUT=10  # API request timeout in seconds
APP_VERSION=1.0.0  # For User-Agent header
CONTACT_EMAIL=admin@example.com  # For User-Agent header (Yr.no requirement)
```

**Get coordinates**: Use [latlong.net](https://www.latlong.net/) to find coordinates for your location.

### Data Structure

Weather is included in the planner dashboard response for each day:

```json
{
  "weather_connected": true,
  "weather_location": "50.0755,14.4378",
  "weather_error": null,
  "days": [
    {
      "date": "2024-12-25",
      "day_name": "Today",
      "weather": {
        "temperature_high": 8.5,
        "temperature_low": 2.1,
        "precipitation": 3.2,
        "symbol_code": "rain",
        "summary": "2.1-8.5°C, 3.2mm rain"
      },
      "events": [...],
      "tasks": [...]
    }
  ]
}
```

### Caching

Weather data is cached in SQLite with a 6-hour TTL to minimize API calls and ensure consistent data across gunicorn workers:
- **Cache table**: `weather_cache` (location → forecast data)
- **TTL**: 6 hours (configurable via `WEATHER_CACHE_TTL_SECONDS`)
- **Shared across workers**: Yes (SQLite-based)
- **Force refresh**: Use `force_refresh=true` parameter on `/api/planner`

### API Terms of Service

Yr.no provides free weather data with these requirements:
- **User-Agent header**: Must identify your application (configured via `APP_VERSION` and `CONTACT_EMAIL`)
- **Rate limiting**: Be respectful - cache data appropriately (we use 6-hour cache)
- **Attribution**: Credit Yr.no when displaying weather data to end users
- **Terms**: https://api.met.no/doc/TermsOfService

### Key Files

**Backend:**
- [weather.py](../../src/utils/weather.py) - Weather fetching from Yr.no API
- [planner_data.py](../../src/utils/planner_data.py) - Weather integration into dashboard
- [models/](../../src/db/models/) - Weather cache operations
- [config.py](../../src/config.py) - Weather configuration

**Migration:**
- [0021_add_weather_cache.py](../../migrations/0021_add_weather_cache.py) - Weather cache table

### Testing

- Unit tests: [test_weather.py](../../tests/unit/test_weather.py) - Weather fetching and caching

### Troubleshooting

**No weather data in planner:**
1. Check `WEATHER_LOCATION` is set in `.env` (format: `lat,lon`)
2. Check `weather_error` field in `/api/planner` response for error messages
3. Verify network connectivity to `api.met.no`
4. Check logs for `"Failed to fetch weather for planner"` messages

**Weather data is stale:**
- Force refresh: Add `?force_refresh=true` to planner API request
- Cache is cleared automatically after 6 hours

## See Also

- [Todoist](todoist.md) and [Google Calendar](google-calendar.md) - the two data sources
- [Planner Dashboard UI](../ui/planner-dashboard.md) - dashboard components and styling
- [Integrations](integrations.md) - all integrations
