# Todoist Integration

Each user connects their own Todoist account via OAuth 2.0 for AI-powered task management.

## Overview

1. **OAuth Flow**: User connects via Settings → Todoist OAuth → token exchange
2. **Token Storage**: Access token stored per-user in the database, encrypted with `TOKEN_ENCRYPTION_KEY`
3. **Tool Availability**: When connected, the `todoist` LangGraph tool is available to the LLM
4. **Tool Capabilities**: Full task/project/section lifecycle management

## OAuth Flow

1. **Authorization URL**: `GET /auth/todoist/auth-url` returns `{auth_url, state}`
2. **State Storage**: The server issues a single-use `state` (kv_store, 10-minute TTL, [oauth_state.py](../../src/auth/oauth_state.py)); the frontend also keeps it in `sessionStorage` to recognise its own callback
3. **Redirect**: User authorizes on Todoist, redirected back to app with `?code=...&state=...`
4. **Callback Handling**: `checkTodoistOAuthCallback()` in SettingsPopup.ts detects the callback
5. **Token Exchange**: `POST /auth/todoist/connect` with `{code, state}` consumes the state server-side, then exchanges the code for a token
6. **User Info**: Backend fetches Todoist user email and stores it with the token

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/todoist/auth-url` | GET | Get OAuth authorization URL and state |
| `/auth/todoist/connect` | POST | Exchange auth code for token |
| `/auth/todoist/disconnect` | POST | Remove Todoist connection |
| `/auth/todoist/status` | GET | Check connection status |

## Todoist Tool Actions

The `todoist` tool exposes granular actions for full Todoist management.

### Task Actions

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

### Project Actions

| Action | Parameters | Description |
|--------|------------|-------------|
| `list_projects` | – | List all projects |
| `get_project` | `project_id` | Fetch project metadata |
| `add_project` | `project_name`, optional `color`, `view_style`, `parent_project_id`, `is_favorite` | Create a project |
| `update_project` | `project_id`, any of the optional project fields | Rename or reconfigure a project |
| `delete_project` | `project_id` | Permanently delete a project |
| `archive_project` / `unarchive_project` | `project_id` | Toggle archive state |

### Section Actions

| Action | Parameters | Description |
|--------|------------|-------------|
| `list_sections` | `project_id` | List sections in a project |
| `get_section` | `section_id` | Fetch a single section |
| `add_section` | `project_id`, `section_name` | Create a section |
| `update_section` | `section_id`, `section_name` | Rename a section |
| `delete_section` | `section_id` | Delete a section |

### Collaborator Actions

| Action | Parameters | Description |
|--------|------------|-------------|
| `list_collaborators` | `project_id` | List all collaborators in a shared project. Returns collaborator IDs, names, and emails for use with task assignment. |

### Todoist Filter Syntax Examples

- `today` - Tasks due today
- `overdue` - Overdue tasks
- `p1` - Priority 1 tasks
- `#Work` - Tasks in Work project
- `today | overdue` - Today's tasks or overdue

### Task Assignment Workflow

For shared projects, the AI can assign tasks to collaborators:

1. **List collaborators**: Use `list_collaborators` with `project_id` to get available assignees
2. **Create assigned task**: Pass `assignee_id` when creating a task with `add_task`
3. **Update assignment**: Use `update_task` with `assignee_id` to reassign or `assignee_id=""` to unassign
4. **View assignments**: `list_tasks` includes `assignee_id` and `assigner_id` in results

**Example user interaction:**
- User: "Add a task 'Review PR' assigned to Alice in the Engineering project"
- AI: Lists collaborators in Engineering project → finds Alice's ID → creates task with `assignee_id`

## Configuration

```bash
# .env
TODOIST_CLIENT_ID=your-client-id
TODOIST_CLIENT_SECRET=your-client-secret
TODOIST_REDIRECT_URI=http://localhost:5173  # Your app URL (use Vite port in dev)
TODOIST_API_TIMEOUT=10  # API request timeout in seconds
```

## Security Notes

- Access tokens are stored per-user in the database, Fernet-encrypted (`TOKEN_ENCRYPTION_KEY`)
- OAuth state is validated server-side and single-use, preventing CSRF / forged callbacks
- Tokens are validated by Todoist on each API call
- Users can disconnect at any time (token is cleared from DB)
- Todoist doesn't support token revocation via API (user must revoke in Todoist settings)
- A token Todoist rejects (`TodoistTokenRejectedError`) makes the tool answer with the shared
  "disconnected - reconnect in Settings" result (see [Integrations](integrations.md#not-connected-results))

## Key Files

**Backend:**
- [config.py](../../src/config.py) - Configuration constants
- [todoist_auth.py](../../src/auth/todoist_auth.py) - OAuth helpers
- [oauth_state.py](../../src/auth/oauth_state.py) - server-side OAuth state
- [models/](../../src/db/models/) - User fields and token management methods
- [tools/todoist.py](../../src/agent/tools/todoist.py) - `todoist()` tool: argument validation + action dispatch table
- [tools/todoist_client.py](../../src/agent/tools/todoist_client.py) - HTTP layer (token lookup, REST + Sync API, `TodoistTokenRejectedError`); the single patch point for tests and the eval fakes
- [tools/todoist_tasks.py](../../src/agent/tools/todoist_tasks.py) / [tools/todoist_projects.py](../../src/agent/tools/todoist_projects.py) - task and project/section actions (task formatting and rejected-filter guidance live with the tasks)
- [routes/todoist.py](../../src/api/routes/todoist.py) - OAuth endpoints
- [prompt_texts/productivity.py](../../src/agent/prompt_texts/productivity.py) - `TOOLS_SYSTEM_PROMPT_PRODUCTIVITY` (Todoist/Calendar behavior; action lists live in the tool docstrings)
- [migrations/0018_add_todoist_fields.py](../../migrations/0018_add_todoist_fields.py) - Database schema

**Frontend:**
- [SettingsPopup.ts](../../web/src/components/SettingsPopup.ts) - UI and OAuth callback handling
- [client.ts](../../web/src/api/client.ts) - API methods
- [api.ts](../../web/src/types/api.ts) - Type definitions
- [popups.css](../../web/src/styles/components/popups.css) - Styles

## Testing

- Integration tests: [test_routes_todoist.py](../../tests/integration/test_routes_todoist.py) - OAuth endpoints
- Eval fakes patch the single HTTP layer in `todoist_client.py` (see [Evals](../testing/evals.md))

## See Also

- [Integrations](integrations.md) - all integrations and the shared not-connected messaging
- [Google Calendar](google-calendar.md) - the other half of the productivity prompt
- [Planner](planner.md) - dashboard combining Todoist tasks and calendar events
- [Setup](../setup.md) - creating the Todoist OAuth app
