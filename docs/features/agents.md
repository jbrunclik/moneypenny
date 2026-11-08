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
| `/api/jobs` | GET | The Command Center's job list (every scheduled item and standing job) |
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
[plan](../superpowers/plans/2026-11-08-standing-chats-phase-2.md). Parts A and B are shipped:
every agent is a standing chat with a standing job (see "Agent Execution Flow").

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

### Settings, approvals and grant levels (standing chats phase 2, Part D)

- **The agent edits its own settings** with `edit_standing_chat`
  (`src/agent/tools/standing_settings.py`): instructions, schedule (cron),
  model, daily budget, fresh context, grants.
  - In its chat it previews first; the change applies on the user's yes in a later turn.
    This is the schedule tool's gate, shared in `src/agent/tools/pending_gate.py`, with kv
    `standing_pending` reserved.
  - In an unattended run it files an approval request and the run pauses. Approving
    applies the change, without rerunning the job.
  - The Daily Briefing's first instructions edit stores the user's own copy of the stock
    prompt; the preview says so.
  - The agent prompt now says the user is away during a run: read and report freely, but
    change nothing lasting and contact no one without an approval.
- **Grant levels** (`src/agent/permissions.py`):
  - `<tool>` lets a run read there; `<tool>:write` also lets it change things, for
    `WRITE_LEVEL_TOOLS` (todoist, google_calendar, garmin_workout, rouvy_workout).
  - A write without the level is a draft: `permission_check` requires one consumed
    approval per change. Every writable tool calls the check itself (Garmin workouts and
    Rouvy included).
  - An approval authorizes only the operation it names (`request_approval(operation=...)`,
    plus `target_id` for destructive ones). An approval naming neither authorizes nothing,
    so an approved "add task" can never be spent on a delete.
  - Destructive operations (Todoist and Calendar deletes, Rouvy delete) still need an
    approval per call, even with `:write`.
  - `*` (all tools) writes.
  - WhatsApp only messages the user, so it is a notification, not a write.
  - Migration 0081 gave existing grants their write levels, so no agent lost a power.
  - The editor sees tool names only; saving keeps the write levels of tools still granted.
- **Always allow:** the approval card's third button ("Always allow Todoist changes"),
  shown for writable integrations, sends `POST /api/approvals/<id>/approve` with
  `{"always": true}`.
  - It adds `<tool>:write` only when the job already holds that tool. A run names the tool
    in its own request, so it can never gain a new tool this way.
  - It is refused for settings changes, and for an approval already handled.
- **Previews expire:** only the user's next message answers a preview (`pending_gate.expired`).
  A preview left behind cannot be confirmed later, for example from a page the agent read.
- An approved settings change is validated again before it applies (`validated_change`).
  `request_approval` cannot file a request under `edit_standing_chat`'s name.

## Agent Execution Flow

Since standing chats phase 2 (Part B, migration 0080) an agent **is** a standing chat plus
a standing job with the agent's id: its run goes through the one items pass
(`run_due_items` -> `run_model_item`, see "Standing jobs" above), not a separate agent
scheduler.

1. **Claim**: the scheduler claims the due job (or Run / an approval resume claims it, so
   two runs never overlap).
2. **Hold**: a job waiting for an approval, or over its daily budget, is given back on its
   schedule without running.
3. **Execution record** in `agent_executions` (`agent_id` = the job id).
4. **History**: the regular chat compaction's view of the chat, including its newest message
   (`run_history(keep_last=True)`); none for `fresh_context` jobs.
5. **Run**: `ChatAgent.chat_batch()` in autonomous mode with the job's grants and model;
   the goals are the chat's standing instructions and data plus the job's task line.
6. **Deliver**: a report is posted into the chat and pushed (titled with the chat);
   `[SILENT]` posts nothing; cost rows carry `job_id`.

**The facade:** `autonomous_agents` is a SQL **view** over `conversations` (the
`standing_*` columns: name, instructions, type, description, unread marker) joined to the
job, so `get_agent`, the Command Center stats and the agents API read unchanged.
`create_agent` / `update_agent` / `delete_agent` write the chat and the job. Part C drops
the view and the agent code (the pre-0080 table is kept as `_autonomous_agents_0080`
for rollback until then).

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

Since standing chats phase 3 the Command Center is **one list of every job**: the
reminders, check-ins, watchers and recurring checks set from chats, and the standing
jobs (agents). It comes from `GET /api/jobs` (`src/api/routes/jobs.py`,
`src/api/helpers/job_responses.py`), rendered by `web/src/components/CommandCenter.ts`.

- **Pending Approvals** sit at the top, as cards with approve and reject buttons and the
  job's schedule.
- **Week stats**: runs, success rate and cost of the jobs' own runs. Shown only when
  there were runs.
- **Jobs**: needs attention first (waiting for approval, paused after failing, last run
  failed), then soonest next run.
  - Each row shows the area or kind icon, the title (an agent's name, or the item's text),
    a status chip, the schedule, the next run, the week's runs and cost for standing jobs,
    and the chat for chat items.
  - **Recent runs** expand from a summary: time, outcome and error, the last 3.
  - Actions: **Run** (standing jobs), **Pause/Resume** (watchers, recurring, agents),
    **Edit** (agents that are not built-in), **Cancel** (chat items).
  - Clicking the row opens the job's chat.
  - Pausing an agent's job disables it (`paused_reason='disabled'`), so the editor and
    the Daily Briefing's Settings toggle agree.
  - A Run is refused while the job waits for an approval or is over its daily budget. So
    are a resume and a `trigger_agent` run (`hold_reason` in `item_scheduler.py`).

### Sidebar Badge

The sidebar shows:
- Unread count badge (total new messages across agent conversations)
- Waiting indicator (pulsing dot when agents need approval)

## Creating an Agent

### By talking (standing chats phase 3, Nov 2026)

In an ordinary chat, "be my cycling coach, check my Garmin every evening at 8 and ask how
I feel" calls `create_standing_chat` (`src/agent/tools/standing_create.py`):

- The first call previews it and creates nothing: name, instructions, the schedule in
  words, and each tool, with write access spelled out ("todoist (can change your
  Todoist)", "garmin_connect (read only)").
- The user's yes in their next message confirms it (the pending gate shared with
  `schedule` and `edit_standing_chat`, namespace `standing_create_pending`). A preview
  left behind expires, and a confirm in the same turn is refused.
- The confirm creates the standing chat and its job with exactly the previewed settings,
  re-checked, and returns the chat's link `#/conversations/<id>`.
- Refused in standing chats and in unattended runs; never bound in anonymous chats. Names
  are unique, and a user has at most `STANDING_CHATS_MAX_PER_USER` standing chats.
- A one-off reminder or watcher stays with `schedule`; the two docstrings point at each
  other. Evals: `standing_create_preview`, `standing_vs_schedule`.

### From the Command Center

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
| `AGENT_MAX_TRIGGER_DEPTH` | 3 | Maximum agent-to-agent trigger chain length (cycles are always blocked) |
| `AGENT_MAX_RETRIES` | 3 | Max retry attempts for transient failures |
| `AGENT_MODEL_SDK_MAX_RETRIES` | 1 | Retries inside the Gemini SDK per chat-model call; a model that is down falls back to the other tier |
| `AGENT_RETRY_BASE_DELAY_SECONDS` | 1.0 | Initial retry delay |
| `AGENT_RETRY_MAX_DELAY_SECONDS` | 30.0 | Maximum retry delay |
| `STANDING_CHATS_MAX_PER_USER` | 10 | Standing chats a user may have; guards against creating them in a loop |
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

- `POST /test/set-jobs-overview` - Set the job list (`GET /api/jobs`) a test renders
- `POST /test/seed-agent` - Seed a real agent (standing chat + job)
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
  const data = await jobs.overview();

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

- [executor.py](../../src/agent/executor.py) - the run context (`AgentContext`, trigger chain), trigger message, run history, approval recording
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
