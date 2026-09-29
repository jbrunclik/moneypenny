# Google Calendar Integration

The assistant orchestrates the user's calendars with strategic time-blocking. Todoist captures actions, Google Calendar blocks time for focused work and commitments.

## Overview

1. **OAuth Flow**: User connects via Settings → Google OAuth → token exchange
2. **Tokens**: Offline access with access + refresh tokens stored per-user
3. **Tool Availability**: When connected, the `google_calendar` tool is available to the LLM
4. **Strategic Approach**: LLM acts as executive strategist, defending focus time and encouraging time-blocking

## OAuth Flow

1. `GET /auth/calendar/auth-url` → returns `{auth_url, state}` (state issued server-side, single-use, 10-minute TTL - [oauth_state.py](../../src/auth/oauth_state.py))
2. User authorizes, Google redirects back with `?code=...&state=...`
3. `checkCalendarOAuthCallback()` validates state and calls `POST /auth/calendar/connect` with `{code, state}`
4. Backend consumes the state, exchanges the code for tokens, fetches the user's Google email, and stores everything (tokens encrypted with `TOKEN_ENCRYPTION_KEY`)
5. Tokens are refreshed automatically in the tool/status endpoint when close to expiry

## Token Refresh and Error Classification

Token refresh lives in one place: `get_valid_access_token(user_id)` in
[auth/google_calendar.py](../../src/auth/google_calendar.py). Everything else is a thin
wrapper over it - `_get_valid_calendar_access_token(user)` in `routes/calendar.py`
(used by the calendar routes, the planner route and tool, and the chat turn setup) and
`_get_google_calendar_access_token()` in `tools/google_calendar.py` (the agent tool).

**Error classes** (`src/auth/google_calendar.py`):

| Exception | When raised | Reconnect required? |
|-----------|-------------|---------------------|
| `GoogleCalendarTokenRevoked` | `invalid_grant` from Google (token permanently revoked) | Yes |
| `GoogleCalendarTransientError` | Network error or Google 5xx | No — retried once |
| `GoogleCalendarAuthError` (base) | Other non-200 responses | Yes |

**Refresh window**: the token is refreshed proactively when it expires within **10 minutes**.

**Retry policy**: a `GoogleCalendarTransientError` is retried once; a second transient
error is re-raised (not treated as reconnect-required).

**Concurrency**: with multiple gunicorn workers two requests can refresh at once. The
refreshed token is stored with a compare-and-swap on the refresh token actually used, so
the loser returns its (valid) access token without overwriting the winner's possibly
rotated refresh token.

**`/auth/calendar/status` behavior**: `needs_reconnect` is set to `True` only when:
- The refresh token is missing, or
- Refresh fails with `GoogleCalendarTokenRevoked` or `GoogleCalendarAuthError`

Transient errors do **not** set `needs_reconnect` — the connection remains valid and will succeed when Google recovers.

**401 retry in API calls**: `_google_calendar_api_request()` in `tools/google_calendar.py`
retries once on HTTP 401 with a freshly fetched token (`_retry_on_401=False` prevents
recursion). A second 401 raises `CalendarDisconnectedError`, which the tool turns into the
shared "disconnected - reconnect in Settings" result
(see [Integrations](integrations.md#not-connected-results)).

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/calendar/auth-url` | GET | Generate Google OAuth URL + CSRF state |
| `/auth/calendar/connect` | POST | Exchange authorization code for tokens |
| `/auth/calendar/disconnect` | POST | Remove stored tokens |
| `/auth/calendar/status` | GET | Report connection status (email, connected_at, needs_reconnect) |
| `/auth/calendar/calendars` | GET | List the user's calendars (cached 1 hour) |
| `/auth/calendar/selected-calendars` | GET / PUT | Read / save the calendars included in the planner |

## Google Calendar Tool Actions

| Action | Parameters | Description |
|--------|------------|-------------|
| `list_calendars` | – | Show calendars accessible to the user |
| `list_events` | `calendar_id`, optional `time_min`, `time_max`, `max_results`, `query` | List upcoming events (defaults to next 7 days) |
| `get_event` | `calendar_id`, `event_id` | Fetch a single event |
| `create_event` | `calendar_id`, `summary`, `start_time`, `end_time` (or `all_day`), optional `timezone`, `attendees`, `location`, `reminders`, `recurrence`, `conference`, `send_updates` | Schedule new events or focus blocks |
| `update_event` | `calendar_id`, `event_id`, any editable fields | Reschedule/rename/update attendees/reminders |
| `delete_event` | `calendar_id`, `event_id`, optional `send_updates` | Delete an event (confirm first) |
| `respond_event` | `calendar_id`, `event_id`, `response_status` | RSVP to invitations (accepted/tentative/declined) |

## Strategic Guidance

The LLM acts as an executive strategist:
- Defends focus time and encourages time-blocking for high-impact tasks
- Assesses impact vs urgency before adding tasks
- Proactively suggests calendar blocks for important work
- Warns about conflicts with focus blocks and suggests alternatives

## Multi-Calendar Selection

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

## Configuration

```bash
# .env
GOOGLE_CALENDAR_CLIENT_ID=your-google-oauth-client-id
GOOGLE_CALENDAR_CLIENT_SECRET=your-google-client-secret
GOOGLE_CALENDAR_REDIRECT_URI=http://localhost:5173   # Vite dev server in development
GOOGLE_CALENDAR_API_TIMEOUT=10
```

## Billing & OAuth Client Reuse

**Billing impact:** Google Calendar API is **free** for personal use with generous quotas (1,000,000 queries/day). There is no cost impact for enabling this integration.

**OAuth client reuse:** The Google Calendar integration uses a **separate OAuth client** from Google Sign-In authentication. This is intentional:

- **Sign-In client**: Only requests `openid email profile` scopes for authentication
- **Calendar client**: Requests `calendar` and `calendar.events` scopes for full calendar access
- **Why separate**: Combining scopes in a single client would require re-authenticating all users when adding calendar features. Separate clients allow incremental opt-in.

If you're setting up a new deployment, you'll need to create two OAuth clients in Google Cloud Console:
1. **Web application** for Sign-In (with `http://localhost:5173` and production URLs as authorized origins)
2. **Web application** for Calendar (with `http://localhost:5173` and production URLs as authorized redirect URIs)

Both clients can be in the same Google Cloud project and share the same OAuth consent screen.

## Key Files

**Backend:**
- [config.py](../../src/config.py) - Configuration constants
- [google_calendar.py](../../src/auth/google_calendar.py) - OAuth helpers: authorize, exchange, and the shared `get_valid_access_token` refresh (error classes)
- [routes/calendar.py](../../src/api/routes/calendar.py) - OAuth endpoints, status endpoint, and exported `_get_valid_calendar_access_token` helper
- [tools/google_calendar.py](../../src/agent/tools/google_calendar.py) - `google_calendar` LangGraph tool (401 retry via `_retry_on_401`, `CalendarDisconnectedError`)
- [tools/planner.py](../../src/agent/tools/planner.py) - Uses `_get_valid_calendar_access_token` for token retrieval
- [prompt_texts/productivity.py](../../src/agent/prompt_texts/productivity.py) - Prompt instructions for calendar + strategic productivity heuristics
- [migrations/0019_add_google_calendar_fields.py](../../migrations/0019_add_google_calendar_fields.py) - Database schema

**Frontend:**
- [SettingsPopup.ts](../../web/src/components/SettingsPopup.ts) - UI and OAuth callback handling
- [client.ts](../../web/src/api/client.ts) - API methods
- [api.ts](../../web/src/types/api.ts) - Type definitions
- [popups.css](../../web/src/styles/components/popups.css) - Styles (includes `.login-privacy-link`)
- [init.ts](../../web/src/core/init.ts) - Login overlay (includes Privacy Policy link)

**Templates:**
- [templates/privacy.html](../../src/templates/privacy.html) - Privacy policy page (required for Google OAuth consent screen verification)

## Privacy Policy Page

A `/privacy` route is registered in `src/app.py` and serves `src/templates/privacy.html`. This page is required when moving a Google Cloud OAuth app from **Testing** to **Production** status (Google verifies that a privacy policy URL is publicly accessible). The login overlay also links to this page via the `.login-privacy-link` element in `init.ts`.

## UX Notes

- Settings popup mirrors Todoist with dedicated Google Calendar card (loading, connected, reconnect, disconnected states)
- OAuth callbacks share the same pattern: store `state` in sessionStorage, validate on return, show toasts
- Thinking indicator metadata includes a `calendar` icon so users can see when the LLM is scheduling/rescheduling

## Testing

- Integration tests: [test_routes_calendar.py](../../tests/integration/test_routes_calendar.py) — OAuth flow, status endpoint (transient/revoked/no-refresh-token scenarios)
- Unit tests: [test_calendar_token_refresh.py](../../tests/unit/test_calendar_token_refresh.py) — shared refresh helper; [test_planner.py](../../tests/unit/test_planner.py) — planner tool mocks `_get_valid_calendar_access_token`

## See Also

- [Integrations](integrations.md) - all integrations and the shared not-connected messaging
- [Todoist](todoist.md) - task side of the productivity prompt
- [Planner](planner.md) - dashboard combining calendar events and tasks
- [Authentication](../architecture/authentication.md) - Google Sign-In (a separate OAuth client)
- [Setup](../setup.md) - creating the Calendar OAuth client
