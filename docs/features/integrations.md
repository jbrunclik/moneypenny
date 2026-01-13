# Integrations

The app integrates with Todoist and Google Calendar for AI-powered task and time management.

## Todoist Integration

Each user connects their own Todoist account via OAuth 2.0 for AI-powered task management.

### Overview

1. **OAuth Flow**: User connects via Settings → Todoist OAuth → token exchange
2. **Token Storage**: Access token stored per-user in database
3. **Tool Availability**: When connected, the `todoist` LangGraph tool is available to the LLM
4. **Tool Capabilities**: Full task/project/section lifecycle management

### OAuth Flow

1. **Authorization URL**: `GET /api/todoist/auth-url` returns `{auth_url, state}`
2. **State Storage**: Frontend stores `state` in `sessionStorage` for CSRF protection
3. **Redirect**: User authorizes on Todoist, redirected back to app with `?code=...&state=...`
4. **Callback Handling**: `checkTodoistOAuthCallback()` in SettingsPopup.ts detects the callback
5. **Token Exchange**: `POST /api/todoist/connect` with `{code, state}` exchanges code for token
6. **User Info**: Backend fetches Todoist user email and stores it with the token

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/todoist/auth-url` | GET | Get OAuth authorization URL and state |
| `/api/todoist/connect` | POST | Exchange auth code for token |
| `/api/todoist/disconnect` | POST | Remove Todoist connection |
| `/api/todoist/status` | GET | Check connection status |

### Todoist Tool Actions

The `todoist` tool exposes granular actions for full Todoist management.

#### Task Actions

| Action | Parameters | Description |
|--------|------------|-------------|
| `list_tasks` | `filter_string` (optional), `project_id` (optional) | List tasks using Todoist filter syntax and enrich with project/section names. Returns `assignee_id` and `assigner_id` if task is assigned. |
| `get_task` | `task_id` | Fetch a specific task |
| `add_task` | `content`, optional `description`, `project_id`, `section_id`, `due_string`, `due_date`, `priority`, `labels`, `assignee_id` | Create a task. Use `assignee_id` to assign to a collaborator. |
| `update_task` | `task_id`, optional task fields including `assignee_id` | Update task properties. Use `assignee_id=""` to unassign. |
| `move_task` | `task_id` and exactly ONE of: `section_id`, `project_id`, or `parent_id` | Move task to a different section (within project), project, or make it a subtask. Uses Sync API since REST API doesn't support moving. |
| `complete_task` | `task_id` | Mark task complete |
| `reopen_task` | `task_id` | Reopen a completed task |
| `delete_task` | `task_id` | Delete a task |

#### Project Actions

| Action | Parameters | Description |
|--------|------------|-------------|
| `list_projects` | – | List all projects |
| `get_project` | `project_id` | Fetch project metadata |
| `add_project` | `project_name`, optional `color`, `view_style`, `parent_project_id`, `is_favorite` | Create a project |
| `update_project` | `project_id`, any of the optional project fields | Rename or reconfigure a project |
| `delete_project` | `project_id` | Permanently delete a project |
| `archive_project` / `unarchive_project` | `project_id` | Toggle archive state |

#### Section Actions

| Action | Parameters | Description |
|--------|------------|-------------|
| `list_sections` | `project_id` | List sections in a project |
| `get_section` | `section_id` | Fetch a single section |
| `add_section` | `project_id`, `section_name` | Create a section |
| `update_section` | `section_id`, `section_name` | Rename a section |
| `delete_section` | `section_id` | Delete a section |

#### Collaborator Actions

| Action | Parameters | Description |
|--------|------------|-------------|
| `list_collaborators` | `project_id` | List all collaborators in a shared project. Returns collaborator IDs, names, and emails for use with task assignment. |

#### Todoist Filter Syntax Examples

- `today` - Tasks due today
- `overdue` - Overdue tasks
- `p1` - Priority 1 tasks
- `#Work` - Tasks in Work project
- `today | overdue` - Today's tasks or overdue

#### Task Assignment Workflow

For shared projects, the AI can assign tasks to collaborators:

1. **List collaborators**: Use `list_collaborators` with `project_id` to get available assignees
2. **Create assigned task**: Pass `assignee_id` when creating a task with `add_task`
3. **Update assignment**: Use `update_task` with `assignee_id` to reassign or `assignee_id=""` to unassign
4. **View assignments**: `list_tasks` includes `assignee_id` and `assigner_id` in results

**Example user interaction:**
- User: "Add a task 'Review PR' assigned to Alice in the Engineering project"
- AI: Lists collaborators in Engineering project → finds Alice's ID → creates task with `assignee_id`

### Configuration

```bash
# .env
TODOIST_CLIENT_ID=your-client-id
TODOIST_CLIENT_SECRET=your-client-secret
TODOIST_REDIRECT_URI=http://localhost:5173  # Your app URL (use Vite port in dev)
TODOIST_API_TIMEOUT=10  # API request timeout in seconds
```

**Important**: Keep `.env.example` updated when adding new environment variables.

### Security Notes

- Access tokens are stored per-user in the database
- OAuth state parameter prevents CSRF attacks
- Tokens are validated by Todoist on each API call
- Users can disconnect at any time (token is cleared from DB)
- Todoist doesn't support token revocation via API (user must revoke in Todoist settings)

### Key Files

**Backend:**
- [config.py](../../src/config.py) - Configuration constants
- [todoist_auth.py](../../src/auth/todoist_auth.py) - OAuth helpers
- [models.py](../../src/db/models.py) - User fields and token management methods
- [tools.py](../../src/agent/tools.py) - `todoist()` tool with context helpers
- [routes.py](../../src/api/routes.py) - OAuth endpoints, context setup
- [chat_agent.py](../../src/agent/chat_agent.py) - `TODOIST_SYSTEM_PROMPT`
- [migrations/0018_add_todoist_fields.py](../../migrations/0018_add_todoist_fields.py) - Database schema

**Frontend:**
- [SettingsPopup.ts](../../web/src/components/SettingsPopup.ts) - UI and OAuth callback handling
- [client.ts](../../web/src/api/client.ts) - API methods
- [api.ts](../../web/src/types/api.ts) - Type definitions
- [popups.css](../../web/src/styles/components/popups.css) - Styles

---

## Google Calendar Integration

The assistant orchestrates the user's calendars with strategic time-blocking. Todoist captures actions, Google Calendar blocks time for focused work and commitments.

### Overview

1. **OAuth Flow**: User connects via Settings → Google OAuth → token exchange
2. **Tokens**: Offline access with access + refresh tokens stored per-user
3. **Tool Availability**: When connected, the `google_calendar` tool is available to the LLM
4. **Strategic Approach**: LLM acts as executive strategist, defending focus time and encouraging time-blocking

### OAuth Flow

1. `GET /auth/calendar/auth-url` → returns `{auth_url, state}`
2. User authorizes, Google redirects back with `?code=...&state=...`
3. `checkCalendarOAuthCallback()` validates state and calls `POST /auth/calendar/connect` with `{code, state}`
4. Backend exchanges the code for tokens, fetches the user's Google email, and stores everything
5. Tokens are refreshed automatically in the tool/status endpoint when close to expiry

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/calendar/auth-url` | GET | Generate Google OAuth URL + CSRF state |
| `/auth/calendar/connect` | POST | Exchange authorization code for tokens |
| `/auth/calendar/disconnect` | POST | Remove stored tokens |
| `/auth/calendar/status` | GET | Report connection status (email, connected_at, needs_reconnect) |

### Google Calendar Tool Actions

| Action | Parameters | Description |
|--------|------------|-------------|
| `list_calendars` | – | Show calendars accessible to the user |
| `list_events` | `calendar_id`, optional `time_min`, `time_max`, `max_results`, `query` | List upcoming events (defaults to next 7 days) |
| `get_event` | `calendar_id`, `event_id` | Fetch a single event |
| `create_event` | `calendar_id`, `summary`, `start_time`, `end_time` (or `all_day`), optional `timezone`, `attendees`, `location`, `reminders`, `recurrence`, `conference`, `send_updates` | Schedule new events or focus blocks |
| `update_event` | `calendar_id`, `event_id`, any editable fields | Reschedule/rename/update attendees/reminders |
| `delete_event` | `calendar_id`, `event_id`, optional `send_updates` | Delete an event (confirm first) |
| `respond_event` | `calendar_id`, `event_id`, `response_status` | RSVP to invitations (accepted/tentative/declined) |

### Strategic Guidance

The LLM acts as an executive strategist:
- Defends focus time and encourages time-blocking for high-impact tasks
- Assesses impact vs urgency before adding tasks
- Proactively suggests calendar blocks for important work
- Warns about conflicts with focus blocks and suggests alternatives

### Multi-Calendar Selection

Users can select which Google Calendars to include in the planner context. By default, only the primary calendar is included.

**Settings UI:**
- List of available calendars with checkboxes
- Visual indicators: color dots, primary star, access role badges
- At least one calendar must be selected (defaults to primary if empty)
- Real-time selection count
- Save button to persist selection (disabled during loading and when no calendars selected)

**Backend:**
- Selected calendar IDs stored as JSON array in `users.google_calendar_selected_ids`
- Events fetched in parallel from selected calendars (max 5 concurrent)
- **Event metadata** included for LLM context:
  - Calendar metadata: `calendar_id`, `calendar_summary` (fetched from Calendar List API)
  - Organizer metadata: `organizer.email`, `organizer.display_name`, `organizer.self`
  - Attendee list with response status
- Automatic deduplication prevents duplicate events if user has redundant calendar IDs selected
- Partial failures handled gracefully (shows events from successful calendars)

**Frontend:**
- Calendar labels displayed on events from non-primary calendars
- Labels styled as pill badges matching project labels in Todoist integration
- Primary calendar events show no label (assumed default)

**Error Handling:**
- Missing/deleted calendar (404): Skipped gracefully
- Permission denied (403): Specific error, continues with others
- Token expired (401): Clear reconnect message
- All calendars fail: Actionable error message
- URL encoding handles special characters in calendar IDs (e.g., `#` in holiday calendars)

**Caching:**
- Available calendars: 1 hour TTL, cleared on connect/disconnect/reconnect
- Dashboard cache: Invalidated on selection change to ensure fresh data

### Configuration

```bash
# .env
GOOGLE_CALENDAR_CLIENT_ID=your-google-oauth-client-id
GOOGLE_CALENDAR_CLIENT_SECRET=your-google-client-secret
GOOGLE_CALENDAR_REDIRECT_URI=http://localhost:5173   # Vite dev server in development
GOOGLE_CALENDAR_API_TIMEOUT=10
```

### Billing & OAuth Client Reuse

**Billing impact:** Google Calendar API is **free** for personal use with generous quotas (1,000,000 queries/day). There is no cost impact for enabling this integration.

**OAuth client reuse:** The Google Calendar integration uses a **separate OAuth client** from Google Sign-In authentication. This is intentional:

- **Sign-In client**: Only requests `openid email profile` scopes for authentication
- **Calendar client**: Requests `calendar` and `calendar.events` scopes for full calendar access
- **Why separate**: Combining scopes in a single client would require re-authenticating all users when adding calendar features. Separate clients allow incremental opt-in.

If you're setting up a new deployment, you'll need to create two OAuth clients in Google Cloud Console:
1. **Web application** for Sign-In (with `http://localhost:5173` and production URLs as authorized origins)
2. **Web application** for Calendar (with `http://localhost:5173` and production URLs as authorized redirect URIs)

Both clients can be in the same Google Cloud project and share the same OAuth consent screen.

### Key Files

**Backend:**
- [config.py](../../src/config.py) - Configuration constants
- [google_calendar.py](../../src/auth/google_calendar.py) - OAuth helpers (authorize, exchange, refresh, userinfo)
- [routes.py](../../src/api/routes.py) - OAuth endpoints and status helpers
- [tools.py](../../src/agent/tools.py) - `google_calendar` LangGraph tool
- [chat_agent.py](../../src/agent/chat_agent.py) - Prompt instructions for calendar + strategic productivity heuristics
- [migrations/0019_add_google_calendar_fields.py](../../migrations/0019_add_google_calendar_fields.py) - Database schema

**Frontend:**
- [SettingsPopup.ts](../../web/src/components/SettingsPopup.ts) - UI and OAuth callback handling
- [client.ts](../../web/src/api/client.ts) - API methods
- [api.ts](../../web/src/types/api.ts) - Type definitions
- [popups.css](../../web/src/styles/components/popups.css) - Styles

### UX Notes

- Settings popup mirrors Todoist with dedicated Google Calendar card (loading, connected, reconnect, disconnected states)
- OAuth callbacks share the same pattern: store `state` in sessionStorage, validate on return, show toasts
- Thinking indicator metadata includes a `calendar` icon so users can see when the LLM is scheduling/rescheduling

---

## Planner Mode

The Planner is a dedicated productivity space that combines Todoist tasks and Google Calendar events into a unified 7-day dashboard. The LLM acts as an executive strategist, providing proactive analysis and recommendations.

### Overview

1. **Daily Planning Session**: Ephemeral conversation that resets at 4am daily
2. **Dashboard Context**: LLM receives structured JSON of upcoming 7 days with tasks and events
3. **Proactive Analysis**: On first load, LLM analyzes schedule and suggests priorities
4. **Strategic Time-Blocking**: LLM helps allocate focus time and balance commitments

### Planner-Specific Tool: refresh_planner_dashboard

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
- Uses `_planner_dashboard_context` contextvar to update dashboard mid-conversation
- System prompt checks contextvar for updated data before using the initial dashboard_data

### Dashboard Data Structure

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

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/planner` | GET | Fetch planner dashboard data (7 days) |
| `/api/planner/conversation` | GET | Get or create planner conversation |
| `/api/planner/reset` | POST | Manually reset planner conversation |
| `/api/planner/sync` | GET | Get planner state for real-time sync |

**Query parameters**:
- `force_refresh=true` - Bypass cache and fetch fresh data (used by refresh button)

### Caching

Dashboard data is cached in SQLite with a 5-minute TTL to improve performance across uwsgi workers:
- Cache key: `planner_dashboard:{user_id}`
- TTL: 5 minutes (configurable via `DASHBOARD_CACHE_TTL_SECONDS`)
- Invalidation: Manual reset or `force_refresh=true` parameter
- Bypass: `refresh_planner_dashboard` tool always fetches fresh data

### Key Files

**Backend:**
- [planner_data.py](../../src/utils/planner_data.py) - Dashboard building logic
- [tools/planner.py](../../src/agent/tools/planner.py) - refresh_planner_dashboard tool
- [routes.py](../../src/api/routes.py) - Planner API endpoints
- [chat_agent.py](../../src/agent/chat_agent.py) - PLANNER_SYSTEM_PROMPT and dashboard context injection
- [models.py](../../src/db/models.py) - Planner conversation management and caching

**Frontend:**
- [PlannerView.ts](../../web/src/components/PlannerView.ts) - Planner container
- [PlannerDashboard.ts](../../web/src/components/PlannerDashboard.ts) - Dashboard rendering
- [planner.css](../../web/src/styles/components/planner.css) - Planner-specific styles

### Testing

- Unit tests: [test_planner.py](../../tests/unit/test_planner.py) - Dashboard building, tool behavior
- E2E tests: [planner.spec.ts](../../web/tests/e2e/planner.spec.ts) - User flows
- Visual tests: [planner.visual.ts](../../web/tests/visual/planner.visual.ts) - Dashboard snapshots

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

Weather data is cached in SQLite with a 6-hour TTL to minimize API calls and ensure consistent data across uwsgi workers:
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
- [models.py](../../src/db/models.py) - Weather cache operations
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

- [Anonymous Mode](memory-and-context.md#anonymous-mode) - Disables integration tools
- [Authentication](../architecture/authentication.md) - OAuth patterns
- [Settings UI](ui-features.md#settings-popup) - Integration connection UI
