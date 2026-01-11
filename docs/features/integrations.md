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
| `list_tasks` | `filter_string` (optional), `project_id` (optional) | List tasks using Todoist filter syntax and enrich with project/section names |
| `get_task` | `task_id` | Fetch a specific task |
| `add_task` | `content`, optional `description`, `project_id`, `section_id`, `due_string`, `due_date`, `priority`, `labels` | Create a task |
| `update_task` | `task_id`, optional task fields | Update task properties |
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

#### Todoist Filter Syntax Examples

- `today` - Tasks due today
- `overdue` - Overdue tasks
- `p1` - Priority 1 tasks
- `#Work` - Tasks in Work project
- `today | overdue` - Today's tasks or overdue

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

## See Also

- [Anonymous Mode](memory-and-context.md#anonymous-mode) - Disables integration tools
- [Authentication](../architecture/authentication.md) - OAuth patterns
- [Settings UI](ui-features.md#settings-popup) - Integration connection UI
