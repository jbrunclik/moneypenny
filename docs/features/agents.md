# Autonomous Agents

Autonomous agents run on cron schedules to perform tasks independently. Each agent has a dedicated conversation showing its activity and can request approval for dangerous operations.

The agent's conversation is a **standing chat** ([spec](../superpowers/specs/2026-11-08-standing-chats-design.md)): when the user writes in it, that is an ordinary chat turn (the normal chat prompt, the user's full chat tools, freshness gate - always at full thinking - the standing chats' context cache (the standard static prompt under its own key, since their tools add `kv_store`) and compaction) plus a `# This Chat: <name>` prompt section with the agent's goals and schedule - see [Talking to an agent](#talking-to-an-agent). Unattended **runs** keep the agent's own grants, approvals and prompt.

## Overview

The autonomous agents feature enables:
- **Scheduled execution**: Agents run automatically based on cron schedules
- **Tool permissions**: Control which tools each agent can use
- **Approval workflow**: Dangerous operations require user approval before execution
- **Agent-to-agent communication**: Agents can trigger other agents via the `trigger_agent` tool
- **Command Center**: Dashboard UI for managing agents and approvals

### When a prompt-only agent suffices

Many watcher/digest-style features (periodically check something, summarize it, notify)
need **no new code and no new tool** — just an agent with a crafted system prompt on a cron
schedule. The default toolset (`web_search`, `fetch_url`, `kv_store`, auto-namespaced per
agent) already covers "fetch, compare against remembered state, report". Before writing a
bespoke tool for a recurring notifier, check whether a prompt-only agent can do it.

Prompt guidance for these agents:
- Make **line 1 of the response a plain-text headline** — the push-notification body is the
  first line of the agent's response (truncated to ~160 chars).
- Pair `fresh_context` with `kv_store` so the agent keeps state across runs (last value seen,
  rolling history) rather than re-deriving it every time.
- Forbid writing guessed/placeholder data to `kv_store` on a fetch failure, and state units
  and formats explicitly so the model does not silently transform values.

## Architecture

### Database Schema

The feature adds three tables:

```sql
-- Autonomous agents
autonomous_agents (
    id PRIMARY KEY,
    user_id REFERENCES users(id),
    conversation_id REFERENCES conversations(id),
    name NOT NULL,
    description,
    system_prompt,
    schedule,
    timezone DEFAULT 'UTC',
    enabled DEFAULT 1,
    tool_permissions,
    model DEFAULT 'gemini-3-flash-preview',
    budget_limit,
    created_at NOT NULL,
    updated_at NOT NULL,
    last_run_at,
    next_run_at,
    last_viewed_at,
    fresh_context DEFAULT 0,   -- 0038: run without prior history (report-style agents)
    system_type,               -- 0039: system-managed agents, e.g. 'daily_briefing'
    UNIQUE(user_id, name)
)

-- Approval requests (blocks execution until resolved or expired)
agent_approval_requests (
    id PRIMARY KEY,
    agent_id REFERENCES autonomous_agents(id),
    user_id REFERENCES users(id),
    tool_name NOT NULL,
    tool_args,
    description NOT NULL,
    status DEFAULT 'pending',
    created_at NOT NULL,
    resolved_at,
    expires_at
)

-- Execution history
agent_executions (
    id PRIMARY KEY,
    agent_id REFERENCES autonomous_agents(id),
    status NOT NULL,
    trigger_type NOT NULL,
    triggered_by_agent_id,
    started_at NOT NULL,
    completed_at,
    error_message
)
```

Conversations are extended with `is_agent` and `agent_id` fields.

### Backend Modules

| Module | Purpose |
|--------|---------|
| `src/db/models/agent.py` | Database CRUD for agents |
| `src/db/models/agent_schedule.py` | Cron next-run math, due agents, last/next run updates |
| `src/db/models/agent_approvals.py` | Approval requests (create, resolve, consume) |
| `src/db/models/agent_executions.py` | Execution tracking, cooldown, zombie cleanup |
| `src/db/models/agent_conversation.py` | Agent conversation, unread state |
| `src/db/models/agent_stats.py` | Command center, observability stats, spend/budget |
| `src/api/routes/agents.py` | REST API: agent CRUD and execution |
| `src/api/routes/agent_command_center.py` | REST API: command center dashboard |
| `src/api/routes/agent_approvals.py` | REST API: approval list/approve/reject |
| `src/api/routes/agent_assist.py` | REST API: AI assist (schedule parsing, prompt enhancer) |
| `src/api/helpers/agent_responses.py` | Agent/execution/approval response dicts |
| `src/agent/executor.py` | Agent execution engine |
| `src/agent/permissions.py` | Tool permission checking |
| `src/agent/daily_briefing.py` | Stock prompt for the system-managed Daily Briefing agent |
| `src/agent/standing_context.py` | The agent chat's standing context when the user writes in it |
| `src/agent/retry.py` | Transient failure retry logic (used per model call by the graph) |
| `src/agent/dev_scheduler.py` | Development mode scheduler |
| `scripts/run_agent_scheduler.py` | Production scheduler script |

### Frontend Modules

| Module | Purpose |
|--------|---------|
| `web/src/core/agents.ts` | Navigation and state management |
| `web/src/core/startup/navigation.ts` | Hands conversation selection the agents view's leaver and the agent header's back/edit actions (F1) |
| `web/src/components/CommandCenter.ts` | Dashboard UI |
| `web/src/components/AgentEditor.ts` | Create/edit modal |
| `web/src/styles/components/agents.css` | Styling |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/agents` | GET | List user's agents |
| `/api/agents` | POST | Create agent (auto-creates conversation) |
| `/api/agents/<id>` | GET | Get agent details |
| `/api/agents/<id>` | PATCH | Update agent |
| `/api/agents/<id>` | DELETE | Delete agent + conversation |
| `/api/agents/<id>/run` | POST | Manual trigger |
| `/api/agents/<id>/mark-viewed` | POST | Mark agent's conversation as viewed |
| `/api/agents/<id>/executions` | GET | Execution history |
| `/api/agents/<id>/conversation/sync` | GET | Sync agent conversation state |
| `/api/agents/command-center` | GET | Dashboard data |
| `/api/agents/approvals` | GET | All pending approvals |
| `/api/ai-assist/parse-schedule` | POST | Helper to parse/validate cron strings |
| `/api/ai-assist/enhance-prompt` | POST | AI helper to refine system prompts |
| `/api/approvals/<id>/approve` | POST | Approve request |
| `/api/approvals/<id>/reject` | POST | Reject request |

## Tool Permissions

Agents are configured with `tool_permissions`; the tool table, permission semantics, the three layers that decide availability, and the checklist for adding a tool are in [Agent Tools](agent-tools.md).

## LLM-Driven Approval System

Agents decide when to request approval using the `request_approval` tool. The agent's system prompt includes guidelines for when approval is appropriate:

- Destructive or irreversible actions
- External communication (sending emails, messages)
- Operations that modify important data
- Anything the user should be aware of before proceeding

When an agent calls `request_approval`:

1. Execution halts immediately via `ApprovalRequestedException`
2. An approval request is created in the database with an expiration
3. The agent's status changes to `waiting_approval`
4. The user sees the request in the Command Center
5. On approval: the paused execution is closed as `completed`, an
   `[Action approved: ...]` message joins the agent's conversation, and the
   agent re-runs in a new execution with access to the approval state. A crash
   in that re-run is recorded on its execution (`failed`); the approval itself
   still succeeds.
6. On rejection: the paused execution fails with "Action rejected by user" and
   an `[Action rejected: ...]` message joins the conversation.

Tests: `tests/integration/test_routes_agent_approvals.py` (the approval flow),
`tests/unit/test_scheduler.py` (due, skipped, failed and resumed runs).

**Note:** Approval requests expire after `AGENT_APPROVAL_TTL_HOURS` (default 24 hours). Expired requests block the agent until resolved or cleaned up.

## Scheduling

### Cron Format

Schedules use standard cron format: `minute hour day-of-month month day-of-week` (e.g., `0 9 * * *` for daily at 9:00 AM).

### Development Mode

In development (`FLASK_ENV=development`), `start_dev_scheduler()` runs a background loop every **60 seconds** (`SCHEDULER_INTERVAL_SECONDS`) to evaluate and execute scheduled agents.

### Production Mode

In production a systemd timer runs `scripts/run_agent_scheduler.py` every minute to check for due agents (see [Scheduled Jobs](../architecture/scheduled-jobs.md)). Never run a scheduler thread inside the web workers.

## Lightweight Agents From Chat (Nov 2026)

The `schedule` tool (`src/agent/tools/scheduling.py`, every non-anonymous chat but the
planner - standing chats included - and never unattended runs, so a scheduled run cannot
schedule more) sets four kinds of item from a
message, each belonging to the chat that set it
([spec](../superpowers/specs/2026-11-07-lightweight-agents-design.md)):

| Kind | Example | Runs | Ends |
|---|---|---|---|
| `reminder` | "remind me Friday at 8 to call the plumber" | push at the time, no model call | once fired |
| `check_in` | "check with me Friday how it's healing" | posts its question into the chat, no model call (written at creation) | once fired |
| `watcher` | "tell me when the school posts a teacher job" | model run every 6h / daily / weekly | `[DONE]`, its end date, or 30 days |
| `recurring` | "every Monday, what's for lunch at school" | model run on a cron (household timezone) | cancelled, or its end date |

- **Confirmed in chat, enforced in code:** `create` without `confirm=true` returns a
  `PREVIEW:` (saying how the item ends), stores nothing, and keeps the preview pending for
  the conversation (kv `schedule_pending`). `confirm=true` stores exactly that pending
  item, and only once a newer user message exists - so a page's injected "confirm" in the
  same turn, or fields that drifted since the preview, cannot schedule something the user
  never saw. `text` and a watcher's `end_condition` go through the injection scan.
- **Built by code:** the model fills structured fields and `src/utils/schedule_spec.py`
  builds the instant, interval or cron string in `Config.APP_TIMEZONE` (a time already
  past is refused, naming the local time).
- **Data:** `scheduled_items` (migration 0076; `src/db/models/scheduled_items.py`), one
  row per item with a required `conversation_id`. Items **follow their chat by query**:
  only items in live chats (not trashed, not archived) are listed, counted or run, so
  trashing or archiving a chat suspends its items and restoring it brings them back; a
  trigger deletes them with the conversation row (permanent delete, trash purge). Finished
  items are deleted - the chat holds the record. `expires_at` holds only an end date the
  user gave; a watcher without one stops `SCHEDULE_WATCH_EXPIRY_DAYS` after it was set
  (`watch_expiry`).
- **Scheduler** (`src/agent/item_scheduler.py`, every minute, before agents): hands back
  runs that never finished (`SCHEDULE_RUN_STALE_MINUTES`; counted as a failure, so a run
  that always dies stops), then claims due items in one `UPDATE ... RETURNING`
  (overlapping runs never handle one twice). One-offs go first; no watcher or recurring
  run starts after `SCHEDULE_TICK_BUDGET_SECONDS` (240 - the scheduler service is killed
  at 300 s and agents run after items), the rest wait for the next tick. A bare `[DONE]`
  still delivers "Found: ..."; an empty report counts as silent. A one-off more than
  `SCHEDULE_MISSED_GRACE_HOURS` late (scheduler down, chat restored after the time) is not
  fired late but noted as "Missed (was due ...)" in its chat. A quiet watcher slows down
  - its interval doubles per `SCHEDULE_WATCH_SLOWDOWN_AFTER_RUNS` silent runs, up to
  weekly, except with a user-given end date; the next run never passes the expiry.
  `SCHEDULE_ITEM_MAX_FAILURES` failed runs in a row, or the end date, stop the item with a
  note in its chat (no push). The run line logs `items_fired`, `items_run`,
  `items_missed`, `items_expired`.
- **Runs** (`src/agent/item_runner.py`): ChatAgent in autonomous mode with an in-memory
  agent (no agent row) and only `web_search`, `fetch_url`, `research`; the user's
  memories are kept out (an unattended run reads untrusted pages), and a stored report
  that looks like injected instructions is not replayed. The run prompt
  (`prompt_texts/scheduled_items.py`) gets what to check, the end condition and the
  previous report; it replies `[SILENT]` (nothing posted or pushed), a report, or for a
  watcher `[DONE]` + report. Cost is recorded against the item's chat - on the delivered
  turn, or for a silent run under a `silent:` message id.
- **Delivery:** a result is an ordinary assistant message in the item's chat with a
  `delivery` label (`{"kind", "label"}`, e.g. "Check-in · Fri 18:00", "Watcher · found"),
  plus a push opening the chat - so the user just replies, in context. Reminders push
  only.
- **UI:** a header chip in the chat (desktop and mobile, agent and program chats too;
  `ScheduleIndicator.ts`) opens a
  sheet listing its items with cancel, and pause/resume for watchers and recurring checks;
  the Command Center has a "From chats" lane above the agents (hidden when empty).
  API: `GET /api/conversations/<id>/schedules`, `DELETE /api/schedules/<id>`,
  `POST /api/schedules/<id>/pause|resume`, `chat_items` on the Command Center payload.
- **Limits:** at most `SCHEDULE_MAX_ACTIVE_PER_USER` (20) items per user, paused included
  (the cap gates creating; restoring trashed or archived chats can bring a user above it -
  their items come back as they were rather than being dropped);
  a reminder's preview warns when none of the user's devices has notifications on.
- **Silent runs** (full agents too): the autonomous-agent prompt says to reply exactly
  `[SILENT]` when a check finds nothing new; the executor saves it as "Nothing new." and
  skips the push (`is_silent_reply`, `should_push_run`).
- Evals: `schedule_reminder_preview`, `schedule_reminder_confirm`, `schedule_check_in_preview`,
  `schedule_watcher_preview`, `schedule_weekly_task`.

### Standing jobs (Nov 2026, standing chats phase 2)

A scheduled item with `grants` set is a **standing job**: an agent's schedule.
[Spec](../superpowers/specs/2026-11-08-standing-chats-design.md),
[plan](../superpowers/plans/2026-11-08-standing-chats-phase-2.md). Part A is shipped. The
agents move onto standing jobs in Part B; until then nothing creates one except tests.

- **Columns** (migration 0078): `grants` (tool names, or `["*"]` for all tools), `model`,
  `budget_usd` (daily), `fresh_context`, `timezone` (the cron's zone), `paused_reason`.
  `message_costs.job_id` attributes an unattended run's cost to its job.
- **Run** (`run_model_item` in `src/agent/item_runner.py`, one path for light items and
  jobs):
  - A job gets its grants plus the safe basics, `request_approval` and `kv_store`, never the
    user's full tools.
  - It also gets its model, the chat's standing context (`src/agent/standing_context.py`),
    and the chat's history unless `fresh_context`.
  - It sees the user's memories only when `manage_memory` (or `*`) is granted.
  - Its synthetic `Agent` carries the job's id, so execution rows and approval requests
    name the job.
- **Light items in a standing chat** (agent, sports or language) see that chat's instructions
  and state, so a coach's check-in knows the program. Their tools stay web-only.
- **Limits** (`src/agent/item_scheduler.py`):
  - no expiry and no slow-down; any cron, evaluated in the job's timezone;
  - not counted toward the 20-item cap;
  - waits while an approval it asked for is pending;
  - a run over its daily budget (`job_spend_today`: its own runs only, not the user's turns
    in the chat) is skipped and recorded, not counted as a failure;
  - after `SCHEDULE_ITEM_MAX_FAILURES` it pauses with one alert ("Paused after 3 failed
    runs: ...") and one push, keeping its setup. Resume clears the failures.
- **API:** `POST /api/schedules/<id>/run` runs a job now (409 for light items, or while
  running or awaiting approval); `ScheduledItemResponse` has `standing` and `paused_reason`.
  Approving a job's request resumes it through `run_job_now` with "[Action approved: ...]".
- **UI:** the schedule chip's sheet shows Run for a job and "paused after failing".

## Agent Execution Flow

1. **Check pending approvals**: Skip if agent has an unresolved/unexpired approval request
2. **Check budget limit**: Skip if agent has exceeded its daily budget
3. **Create execution record**: Track the run in `agent_executions`
4. **Load conversation history**: The regular chat compaction's view of the conversation (`build_compacted_history()`; skipped for `fresh_context` agents, which run each turn from a clean slate)
5. **Set up ChatAgent**: Configure with agent's tools and permissions
6. **Run the turn**: `ChatAgent.chat_batch()` in autonomous mode (model calls are retried inside the graph, see below)
7. **Save messages**: Add user trigger and assistant response (with source chips from `extract_read_sources()`, generated files and cost) to the conversation
8. **Update timestamps**: Set `last_run_at` and calculate `next_run_at`

## Conversation Compaction

Runs and the user's own turns in an agent chat share the regular, non-destructive chat compaction (a running summary plus recent messages; nothing is deleted). The destructive agent compaction and its `AGENT_COMPACTION_*` settings were removed in Nov 2026. Details: [Conversation Context](../architecture/conversation-context.md#conversation-compaction).

## Talking to an Agent

Writing in an agent's chat is an ordinary chat turn, not a run: `load_standing_context()`
([standing_context.py](../../src/agent/standing_context.py)) builds a
`StandingContext` ([standing.py](../../src/agent/standing.py)) with the agent's goals
(`resolve_agent_system_prompt()`, so the Daily Briefing's stock prompt comes from code)
and a plain description of its schedule, rendered as the `# This Chat: <name>` section by
`format_standing_section()` ([prompts.py](../../src/agent/prompts.py), text in
`prompt_texts/standing.py`). The turn binds the user's chat tools plus `kv_store`
defaulting to the agent's `agent:<id>` namespace; the agent's `tool_permissions` and the
unattended approval gate do not apply while the user is present. A pending approval from a
run still blocks sending (`prepare_turn` refuses with a validation error until it is
resolved). Eval: `agent_chat_remind_me`.

## Transient Failure Retries

Transient model errors (connection errors, timeouts, rate limits, 503s) are retried with exponential backoff and jitter **per model call** inside the graph chat node (`AGENT_MAX_RETRIES`, `AGENT_RETRY_BASE_DELAY_SECONDS`, `AGENT_RETRY_MAX_DELAY_SECONDS`). The executor deliberately has no whole-run retry: replaying a turn would re-execute non-idempotent tools (Todoist/Calendar writes, WhatsApp sends). See [Agent Graph](../architecture/agent-graph.md#chat-node-and-transient-error-retries).

## Budget Limits

Agents can have per-agent daily spending limits to prevent runaway costs.

**Configuration:**
- Set `budget_limit` in the agent editor (USD per day)
- Leave empty for unlimited spending
- Agents that exceed their daily budget are skipped until the next day

**How it works:**
1. Before execution, check today's total spending for the agent
2. If spending exceeds `budget_limit`, skip execution with an error message
3. Spending resets at midnight UTC each day

## Command Center UI

The Command Center dashboard shows:

- **Pending Approvals**: Cards with approve/reject buttons
- **Your Agents**: Grid of agent cards with status, schedule, unread count
- **Recent Activity**: List of recent executions

### Sidebar Badge

The sidebar shows:
- Unread count badge (total new messages across agent conversations)
- Waiting indicator (pulsing dot when agents need approval)

## Creating an Agent

1. Click the robot icon in the sidebar or navigate to Command Center
2. Click "New Agent"
3. Fill in:
   - **Name**: Unique identifier
   - **Description**: What the agent does
   - **Schedule**: Cron expression or preset
   - **Timezone**: For schedule interpretation
   - **System Prompt**: Agent's goals and behavior
   - **Tool Permissions**: Which tools the agent can use
   - **Enabled**: Toggle to activate/deactivate

## Agent-to-Agent Communication

Agents can trigger other agents using the `trigger_agent` tool:

```python
@tool
def trigger_agent(agent_name: str, message: str = "Continue") -> str:
    """Trigger another autonomous agent to run."""
```

Circular dependencies are prevented via a `trigger_chain` in the agent context - an agent cannot trigger an agent that's already in the current execution chain.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_APPROVAL_TTL_HOURS` | 24 | Hours until approval requests expire |
| `AGENT_EXECUTION_TIMEOUT_MINUTES` | 10 | Max execution time before considered stale |
| `AGENT_EXECUTION_COOLDOWN_SECONDS` | 5 | Minimum seconds between manual runs |
| `AGENT_MAX_TRIGGER_DEPTH` | 3 | Maximum agent-to-agent trigger chain length (cycles are always blocked) |
| `AGENT_MAX_RETRIES` | 3 | Max retry attempts for transient failures |
| `AGENT_MODEL_SDK_MAX_RETRIES` | 1 | Retries inside the Gemini SDK per chat-model call; a model that is down falls back to the other tier |
| `AGENT_RETRY_BASE_DELAY_SECONDS` | 1.0 | Initial retry delay |
| `AGENT_RETRY_MAX_DELAY_SECONDS` | 30.0 | Maximum retry delay |
| `AGENT_MAX_TOOL_RETRIES` | 2 | Max consecutive tool errors before LLM is told to give up |
| `GUNICORN_MAX_REQUESTS` | 1000 | Recycle workers after N requests (memory leak safety net) |
| `GUNICORN_MAX_REQUESTS_JITTER` | 50 | Random jitter to stagger worker recycling |

Agents also use existing configuration for:
- `GEMINI_API_KEY` - LLM access
- `DATABASE_PATH` - Agent storage
- Integration credentials (Todoist, Calendar) if used

### Feature Toggle

Agents are always available for authenticated users. No feature flag required.

## Testing

### Visual Tests

Run visual regression tests:

```bash
cd web && npx playwright test tests/visual/agents.visual.ts
```

Update snapshots:

```bash
cd web && npx playwright test tests/visual/agents.visual.ts --update-snapshots
```

### Test Endpoints (E2E)

In E2E test mode, these endpoints control agent state:

- `POST /test/set-agents-command-center` - Set mock command center data
- `POST /test/clear-agents-config` - Reset to defaults

## Routing Race Condition Prevention

When users rapidly navigate between different views (conversations, planner, agents), async operations
from the first view might complete after the user has already switched to another view. Without
protection, this would render stale content in the wrong view.

### The Navigation Token Pattern

The solution uses a navigation token that increments on each navigation:

```typescript
// In store.ts
navigationToken: number;
startNavigation: () => number;       // Increments and returns new token
isNavigationValid: (token) => boolean; // Checks if token matches current
```

### Usage in Navigation Functions

Each async navigation function follows this pattern:

```typescript
async function navigateToAgents(): Promise<void> {
  // 1. Get token BEFORE async operations
  const navToken = store.startNavigation();

  // 2. Start async load
  const data = await agents.getCommandCenter();

  // 3. Check token AFTER async completes - cancel if invalid
  if (!store.isNavigationValid(navToken)) {
    log.info('User navigated away, aborting render');
    return;
  }

  // 4. Safe to render
  renderCommandCenter(data);
}
```

### Why This Works

- Each navigation increments the token
- If user clicks Agents → Planner → Agents rapidly:
  - First Agents click: token = 1
  - Planner click: token = 2
  - Second Agents click: token = 3
- When first Agents load completes (token was 1, current is 3) → cancelled
- Only the final navigation renders

A navigation with nothing to load must still take a token: `createConversation()`
(New Chat) calls `startNavigation()` first. Without it a New Chat clicked while
the planner was loading (its loading placeholder already carries
`#planner-dashboard`) let the planner render its dashboard over the new chat -
the intermittent `UI state is properly reset when leaving planner` E2E failure
(Oct 2026, 2 of 10 runs).

### Adding New Screens

When adding a new screen:
1. Import `useStore` and call `startNavigation()` before async operations
2. After async completes, check `isNavigationValid(token)` before rendering
3. If invalid, return early without rendering

This pattern automatically handles race conditions with all other screens
without needing screen-specific flag checks.

### Input Area Visibility During Navigation

The agents view hides the input area (since it's not a chat). When navigating away from agents to
other views, the input area must be restored. This is handled by `ensureInputAreaVisible()` in
[MessageInput.ts](../../web/src/components/MessageInput.ts).

**The bug scenario:**
1. User is in agents view (input area hidden)
2. User navigates to planner while it's loading
3. Planner sets `isAgentsView = false` but the async fetch hasn't completed
4. User navigates to a conversation before planner finishes
5. Neither navigation restores the input area → input box invisible

**The fix:**
- `ensureInputAreaVisible()` is a defensive helper that removes `hidden` class from input area
- Called in multiple places to ensure coverage regardless of navigation path:
  - `navigateToPlanner()` - when coming from agents view
  - `switchToConversation()` - defensive call for all conversation switches
  - `createConversation()` - defensive call for new conversations
  - `leaveAgentsView()` - primary restore point when leaving agents
  - `leavePlannerView()` - ensures input visible after leaving planner

**Regression tests:** [navigation-input-focus.test.ts](../../web/tests/unit/navigation-input-focus.test.ts)

## Future Enhancements

- Agent conversation header status and run button (the header currently has back + edit, `AgentConversationHeader.ts`)
- Inline approval display in agent conversations
- Agent execution logs with detailed output
- Webhook triggers for agents
- Agent templates library

## Key Files

- [executor.py](../../src/agent/executor.py) - `execute_agent()`, agent context, trigger chain
- [routes/agents.py](../../src/api/routes/agents.py) - REST endpoints (CRUD, execution)
- [routes/agent_assist.py](../../src/api/routes/agent_assist.py) - AI assist endpoints, `_PROMPT_TOOL_DESCRIPTIONS`
- [models/agent.py](../../src/db/models/agent.py) - agents, approvals, executions
- [dev_scheduler.py](../../src/agent/dev_scheduler.py) / [run_agent_scheduler.py](../../scripts/run_agent_scheduler.py) - scheduling
- [CommandCenter.ts](../../web/src/components/CommandCenter.ts), [AgentEditor.ts](../../web/src/components/AgentEditor.ts), [core/agents.ts](../../web/src/core/agents.ts) - UI
- [test_agents.py](../../tests/unit/test_agents.py), [test_routes_agents.py](../../tests/integration/test_routes_agents.py), [agents.spec.ts](../../web/tests/e2e/agents.spec.ts)

## See Also

- [Agent Tools](agent-tools.md) - tool table, permissions, adding a tool, K/V store, browser
- [Agent Graph](../architecture/agent-graph.md) - the loop every run goes through
- [Push Notifications](push-notifications.md) - how agents notify the user
- [WhatsApp](whatsapp.md) - WhatsApp notifications for agents
- [Scheduled Jobs](../architecture/scheduled-jobs.md) - production scheduling
