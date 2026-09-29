# Integrations

Third-party services the agent can act on. Each has its own page; this one covers what
they share: how their tools get bound and what a user without a working connection sees.

| Integration | Tool(s) | Auth | Page |
|-------------|---------|------|------|
| Todoist | `todoist` | OAuth 2.0, per user | [todoist.md](todoist.md) |
| Google Calendar | `google_calendar` | OAuth 2.0 (separate client from Sign-In), per user | [google-calendar.md](google-calendar.md) |
| Planner (Todoist + Calendar + Yr.no weather) | `refresh_planner_dashboard` (planner mode only) | uses the two above | [planner.md](planner.md) |
| Garmin Connect | `garmin_connect` (read), `garmin_workout` (write) | email/password, session tokens stored | [garmin.md](garmin.md) |
| Rouvy | `rouvy_workout` | headless Playwright login, session cookie stored | [rouvy.md](rouvy.md) |
| WhatsApp (autonomous agents) | `whatsapp` | app-level Meta Cloud API token + per-user phone number | [whatsapp.md](whatsapp.md) |
| Mapy.com places and routing | `search_places`, `get_route`, saved places | app-level API key | [location.md](location.md) |
| Web Push | (agent notifications) | VAPID keys + browser subscription | [push-notifications.md](push-notifications.md) |

Operator setup (creating OAuth clients, API keys) is in [setup.md](../setup.md).

## Tool Binding

Integration tools are bound when the integration is available **server-side**, not
when the current user has connected it (`get_available_tools()` in
[tools/__init__.py](../../src/agent/tools/__init__.py)):

| Tool | Bound when |
|------|------------|
| `todoist` | `is_todoist_available()` - `TODOIST_CLIENT_ID` and `TODOIST_CLIENT_SECRET` set |
| `google_calendar` | `is_google_calendar_available()` - Calendar OAuth client configured |
| `garmin_connect`, `garmin_workout` | `is_garmin_available()` - `garminconnect` package installed |
| `rouvy_workout` | `is_rouvy_available()` - `BROWSER_ENABLED` and Chromium installed |
| `whatsapp` | app-level config complete; agents additionally need the user's phone number (`_is_whatsapp_available_for_user`) |

[Anonymous mode](memory-and-context.md#anonymous-mode) unbinds `todoist`,
`google_calendar`, `garmin_connect` and `garmin_workout` (`_INTEGRATION_TOOLS`), along
with memory, saved-place and conversation-search tools.

## Not-Connected Results

Because the tool stays bound, a user whose connection lapsed still reaches it. The tool
then returns `not_connected_result(integration)` from
[integration_status.py](../../src/agent/tools/integration_status.py), which
distinguishes two cases that need different replies:

- **Was connected, no longer works** (expired session, revoked token) - `"<Label>
  disconnected"`. The user believes it is connected, so the message tells the agent to
  say plainly that it got disconnected and can be reconnected in Settings, and not to
  claim it lacks the capability. (Sep 2026: "Garmin not connected" appeared 14x in 30
  days, mostly expired sessions the agent reported as missing support.)
- **Never connected** - `"<Label> not connected"`: offer to use it once the user
  connects it in Settings.

Both results carry `retriable: False` and tell the agent not to retry the call. Which
case applies is read from the user record: a deliberate disconnect in Settings clears
both the credential (`garmin_token`, `todoist_access_token`,
`google_calendar_access_token`, `rouvy_session`) and `<integration>_connected_at`, so
either one still being present means the connection broke rather than was removed.
Callers that already know - e.g. Todoist just rejected a stored token, or Calendar
answered 401 after a forced refresh - pass `was_connected=True`.

Used by `todoist`, `google_calendar`, `garmin_connect`, `garmin_workout` and
`rouvy_workout`.

## Key Files

- [tools/__init__.py](../../src/agent/tools/__init__.py) - tool binding and anonymous-mode exclusions
- [tools/integration_status.py](../../src/agent/tools/integration_status.py) - `not_connected_result`
- [auth/oauth_state.py](../../src/auth/oauth_state.py) - server-side, single-use OAuth `state` (Todoist, Calendar)
- [utils/token_crypto.py](../../src/utils/token_crypto.py) - Fernet encryption of stored tokens (`TOKEN_ENCRYPTION_KEY`)
- [tests/unit/test_integration_status.py](../../tests/unit/test_integration_status.py) - the two cases

## See Also

- [Anonymous Mode](memory-and-context.md#anonymous-mode) - disables integration tools
- [Authentication](../architecture/authentication.md) - OAuth patterns
- [UI Features](ui-features.md) - settings and connection UI
- [Agent Tools](agent-tools.md) - tool permissions for autonomous agents
