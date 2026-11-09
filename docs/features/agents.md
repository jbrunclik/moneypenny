# Standing Chats and Jobs

A **standing chat** is a chat with standing settings (name, instructions, description,
built-in type) plus a **standing job** with the same id that runs it unattended on a cron
schedule ([spec](../superpowers/specs/2026-11-08-standing-chats-design.md)). The UI still
calls them "agents". Every reminder, check-in, watcher and recurring check set from a chat
is a lighter **job** of the same kind (a `scheduled_items` row without grants); the Command
Center lists them all.

When the user writes in a standing chat, that is an ordinary chat turn (the normal chat
prompt, the user's full chat tools, freshness gate - always at full thinking - the standing
chats' context cache (the standard static prompt under its own key, since their tools add
`kv_store`) and compaction) plus a `# This Chat: <name>` prompt section with the goals and
schedule - see [Talking to a standing chat](#talking-to-a-standing-chat). Unattended
**runs** keep the job's own grants, approvals and instructions.

## Overview

- **Scheduled runs**: a standing job runs on its cron, in its own timezone
- **Grants**: which tools a run may use, and where it may change things (`<tool>:write`)
- **Approvals**: a run asks before anything it may not do on its own
- **Job-to-job handoff**: a run can start another standing job via `trigger_agent`
- **Command Center**: one list of every job, with approvals, Run, Pause/Resume, Edit

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

### Data

There is no agents table (0080 folded it into chats and jobs) and no `autonomous_agents`
view (dropped by 0082). A standing chat is:

- a `conversations` row with `is_agent = 1`, `job_id` (the job's id) and the `standing_*`
  columns (migration 0079): `standing_name`, `standing_instructions` (NULL on a built-in
  means the stock prompt from code), `standing_description`, `standing_type` (e.g.
  `daily_briefing`) and `standing_viewed_at` (the unread marker). `job_id` keeps an inert
  `REFERENCES` clause; foreign keys are never enabled.
- a `scheduled_items` row with the same id and `grants` set (migration 0078): `schedule`
  (cron), `timezone`, `grants`, `model`, `budget_usd`, `fresh_context`, `paused_reason`.
- `users.daily_briefing_job_id` points at the user's Daily Briefing.

```sql
-- One row per run of a job (standing jobs; light items record no runs)
job_runs (
    id PRIMARY KEY,
    item_id REFERENCES scheduled_items(id),
    status NOT NULL,          -- running, completed, failed, waiting_approval
    trigger_type NOT NULL,    -- scheduled, manual, agent, approval
    triggered_by_job_id,
    started_at NOT NULL,
    completed_at,
    error_message
)

-- A run waiting on the user's yes is a run proposal (origin 'run', job_id,
-- execution_id, expires_at, consumed) in proposals - see proposals.md
```

Migration 0082 created both tables fresh from `agent_executions` and
`agent_approval_requests` (rows carried over), renamed the two columns, and dropped the
`autonomous_agents` view and its `_autonomous_agents_0080` backup. Its rollback restores
the old tables and names, the view, and an **empty** backup table, so 0080's own rollback
still rebuilds the agents from the chats and jobs.

### Backend Modules

| Module | Purpose |
|--------|---------|
| `src/db/models/standing_chats.py` | `StandingChatMixin`: create/get/get_by_name/list/update/delete a standing chat (chat + job together), `standing_unread_count`, `mark_standing_viewed`; `next_cron_run` |
| `src/db/models/scheduled_items.py` | Jobs and light items: claim, due, pause, `job_spend_today` |
| `src/db/models/job_runs.py` | `JobRunMixin`: run records, `recent_runs`, `get_job_runs`, zombie cleanup |
| `src/agent/run_approvals.py` | Run cards: the gates file the exact call, answers resume or end the run ([proposals](proposals.md)) |
| `src/db/models/job_rows.py` | Row -> `JobRun` / `ApprovalRequest` |
| `src/api/routes/jobs.py` | REST: the overview, standing chat CRUD, run, runs, viewed, sync; owns the `jobs` blueprint |
| `src/api/routes/approvals.py` | REST: the runs waiting on a card (on the `jobs` blueprint); answered via `/api/proposals` |
| `src/api/routes/schedules.py` | REST: a chat's items, pause/resume/run/cancel |
| `src/api/routes/agent_assist.py` | REST: AI assist (schedule parsing, prompt enhancer) |
| `src/api/schemas/jobs.py`, `agent_assist.py` | Request/response schemas |
| `src/api/helpers/job_responses.py` | The Command Center overview (`jobs_overview`) |
| `src/api/helpers/standing_responses.py` | Standing chat / run / approval response dicts |
| `src/agent/item_scheduler.py` | The scheduler pass, `run_job_now`, `hold_reason` |
| `src/agent/item_runner.py` | `run_model_item`: one run of a watcher, recurring item or standing job |
| `src/agent/run_context.py` | `JobContext` (contextvar), trigger message, run history, approval recording, `[SILENT]` |
| `src/agent/permissions.py` | Grants -> permissions, write levels, permission checks |
| `src/agent/daily_briefing.py` | The built-in Daily Briefing: stock prompt, `effective_instructions`, Settings toggle |
| `src/agent/standing_context.py` | The chat's standing context when the user writes in it |
| `src/agent/retry.py` | Transient failure retry logic (used per model call by the graph) |
| `src/agent/dev_scheduler.py` | Development mode scheduler |
| `scripts/run_agent_scheduler.py` | Production scheduler script |

A run's context is `JobContext(item, user, name, trigger_chain)`
(`get_job_context` / `set_job_context` / `clear_job_context`); its `.permissions` is
`run_permissions(item.grants)`: `["*"]` gives `None` (all tools), `None` or `[]` (a light
item) gives `[]`, otherwise the grants. `check_tool_permission(permissions, ...)` and
`has_write_grant(permissions, tool)` take that list, and `tools_for_grants(grants,
user_id)` ([tools/__init__.py](../../src/agent/tools/__init__.py)) binds the run's tools.

### Frontend Modules

| Module | Purpose |
|--------|---------|
| `web/src/core/agents.ts` | Navigation, Command Center handlers, `handleStandingRun` (the chat header's Run) |
| `web/src/core/startup/navigation.ts` | Hands conversation selection the agents view's leaver and the header's back/edit/run actions (F1) |
| `web/src/components/CommandCenter.ts` | The job list |
| `web/src/components/JobEditor.ts` | Create/edit modal |
| `web/src/components/AgentConversationHeader.ts` | The standing chat's header: back, Run now, edit |
| `web/src/api/jobs.ts` | `jobs`: overview, CRUD, run, runs, viewed, sync, approve/reject |
| `web/src/api/assist.ts` | `aiAssist`: parse schedule, enhance prompt |
| `web/src/state/slices/agents.ts` | The overview (`JobsOverviewResponse`) |
| `web/src/styles/components/agents.css` | Styling |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/jobs` | GET | The Command Center overview (every job, approvals, stats, badge counts) |
| `/api/jobs` | POST | Create a standing chat with its job |
| `/api/jobs/<id>` | GET | A standing chat as the editor shows it (`JobDetailResponse`) |
| `/api/jobs/<id>` | PATCH | Update it (only the fields sent change) |
| `/api/jobs/<id>` | DELETE | Delete the standing chat, its job and its conversation |
| `/api/jobs/<id>/run` | POST | Run now (refused while running, held or awaiting approval) |
| `/api/jobs/<id>/runs` | GET | Run history |
| `/api/jobs/<id>/viewed` | POST | Mark its chat as viewed |
| `/api/jobs/<id>/conversation/sync` | GET | Poll its chat for changes |
| `/api/approvals` | GET | Runs waiting on their card (`job_id`, `job_name`, `conversation_id` + the card) |
| `/api/proposals/<id>/approve` | POST | Approve a run's card (`{"choice": 1}` = Always allow) - see [proposals](proposals.md) |
| `/api/proposals/<id>/decline` | POST | Not now: the run ends |
| `/api/ai-assist/parse-schedule` | POST | Helper to parse/validate cron strings |
| `/api/ai-assist/enhance-prompt` | POST | AI helper to refine instructions |

`JobDetailResponse` carries `instructions` (as stored; null on an unedited built-in),
`effective_instructions` (what runs, `effective_instructions()` in `daily_briefing.py`),
`grants` with write levels as `"<tool>:write"`, `budget_usd`, `standing_type`,
`spend_today_usd`, `has_pending_approval`, `unread_count` and `last_run_status`.
`CreateJobRequest` / `UpdateJobRequest` take `grants` (null = all tools). Conversation
responses carry `job_id` for a standing chat.

## Grants

A job's `grants` decide the tools a run is bound with; the tool table, the three layers
that decide availability, and the checklist for adding a tool are in
[Agent Tools](agent-tools.md).

## LLM-Driven Approval System

Runs decide when to request approval using the `request_approval` tool. The run prompt includes guidelines for when approval is appropriate:

- Destructive or irreversible actions
- External communication (sending emails, messages)
- Operations that modify important data
- Anything the user should be aware of before proceeding

A run that needs the user's yes is parked on a **run card** (a run
proposal, [proposals](proposals.md); `src/agent/run_approvals.py`):

1. The gates file it themselves: a destructive operation, or a write without
   the write level, files the blocked call's card - its tool and full
   arguments (`call_signature`). The call returns "waiting for approval", the
   round's other calls still run, and after the round the tool node pauses
   the run on every card it filed (`pause_on_gated_calls`, raising
   `ApprovalRequestedException`).
   `request_approval` files an unbound card for actions no gate covers;
   `edit_standing_chat` in a run files an `edit_agent` card.
2. `record_approval_request` posts the waiting message ("Waiting for your
   approval") with the round's cards under it and marks the run `waiting_approval`;
   the job waits (the scheduler skips it) and a push goes out.
3. The user answers on the card - in the agent's chat or Command Center's
   "Needs you" - or types yes/no in the agent's chat (only the latest
   reply's unexpired cards take a typed answer). A typed answer is
   answer-only: no chat turn, the resumed run's report is the reply. Any
   other message is a normal turn; the card keeps waiting (the chat no longer
   locks).
4. Each answer leaves a plain `[Action approved/rejected: ...]` note in the
   chat. Once every card of the paused run is answered, the run closes -
   `completed` if anything was approved, then the job re-runs in the
   background (trigger `approval`: its report pushes - the answer may have
   come from a push), told the exact calls to re-issue; `rejected` otherwise. Only
   the identical call consumes an approval, once (`consume_run_approval`;
   a card still applying counts, as the rerun can start first). Always allow
   also grants `<tool>:write`. An approved settings change applies itself,
   no rerun.
5. Not now on every card: the run closes as `rejected`.
6. Unanswered for `AGENT_APPROVAL_TTL_HOURS` (24 h): the card expires and the
   run closes as failed ("The approval was not answered in time") from the
   scheduler tick (`expire_stale_run_cards`).

Tests: `tests/unit/test_destructive_approval_gate.py`,
`tests/unit/test_grant_levels.py`, `tests/unit/test_run_approvals.py`,
`tests/integration/test_routes_approvals.py`,
`tests/integration/test_answer_only_turns.py`.

## Scheduling

### Cron Format

Schedules use standard cron format: `minute hour day-of-month month day-of-week` (e.g., `0 9 * * *` for daily at 9:00), evaluated in the job's `timezone`.

### Development Mode

In development (`FLASK_ENV=development`), `start_dev_scheduler()` runs a background loop every **60 seconds** (`SCHEDULER_INTERVAL_SECONDS`) to run due jobs.

### Production Mode

In production a systemd timer runs `scripts/run_agent_scheduler.py` every minute to check for due jobs (see [Scheduled Jobs](../architecture/scheduled-jobs.md)). Never run a scheduler thread inside the web workers.

## Light Jobs From Chat

Reminders, check-ins, watchers and recurring checks set from a message by the `schedule`
tool are jobs without grants: see [Jobs Set From Chat](scheduled-items.md). They share the
scheduler pass, the run path (`run_model_item`) and the Command Center with standing jobs.

## Standing Jobs

A scheduled item with `grants` set is a **standing job**: a standing chat's schedule
(see "Run Flow").

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
  - Its `JobContext` carries the job, so run records and approval requests name it
    (`item_id`).
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

## Settings, Approvals and Grant Levels

- **The agent edits its own settings** with `edit_standing_chat`
  (`src/agent/tools/standing_settings.py`): instructions, schedule (cron),
  model, daily budget, fresh context, grants.
  - In its chat it files an `edit_agent` [proposal](proposals.md): the card lists the
    change, and the server applies exactly that on **Apply** or a typed yes.
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
  - An approval authorizes only the exact call its card showed (tool + full arguments):
    an approved "add task: Buy milk" can never be spent on other text or a delete.
  - Destructive operations (Todoist and Calendar deletes, Rouvy delete) still need an
    approval per call, even with `:write`.
  - `*` (all tools) writes.
  - WhatsApp only messages the user, so it is a notification, not a write.
  - Migration 0081 gave existing grants their write levels, so no agent lost a power.
  - The editor (`JobEditor.ts`) shows a "Can change things without asking" toggle under
    Todoist and Calendar that sets and clears `<tool>:write`; a write level is only saved
    for a tool that is itself granted. Grants the grid doesn't show (set by talking or an
    approval) are kept on save, and a job with all tools stays unrestricted unless the
    selection is changed.
- **Always allow:** the run card's second option ("Always allow Todoist changes"),
  offered for a write in a writable integration the job already holds (never a delete).
  - It adds `<tool>:write` only when the job holds that tool, so a run can never gain a
    new tool this way.
- **Cards expire:** only the user's next message answers a chat card; anything else
  expires it ([proposals](proposals.md)), so nothing later - say a page the agent read -
  can apply it.
- An approved settings change is validated again before it applies (`validated_change`).
  `request_approval` cannot file a request under `edit_standing_chat`'s name.

## Run Flow

A standing job's run goes through the one items pass (`run_due_items` -> `run_model_item`,
see "Standing jobs" above).

1. **Claim**: the scheduler claims the due job (or Run / an approval resume claims it, so
   two runs never overlap).
2. **Hold**: a job waiting for an approval, or over its daily budget, is given back on its
   schedule without running (`hold_reason`).
3. **Run record** in `job_runs` (`item_id` = the job id).
4. **Context**: a `JobContext` is set for the run, so tools read the job's grants and
   trigger chain.
5. **History**: the regular chat compaction's view of the chat, including its newest message
   (`run_history(keep_last=True)`); none for `fresh_context` jobs.
6. **Run**: `ChatAgent.chat_batch()` in autonomous mode with `tools_for_grants()` and the
   job's model; the goals are the chat's standing instructions (`effective_instructions`)
   and data plus the job's task line.
7. **Deliver**: a report is posted into the chat and pushed (titled with the chat);
   `[SILENT]` posts nothing; cost rows carry `job_id`.

## Conversation Compaction

Runs and the user's own turns in a standing chat share the regular, non-destructive chat compaction (a running summary plus recent messages; nothing is deleted). Details: [Conversation Context](../architecture/conversation-context.md#conversation-compaction).

## Talking to a Standing Chat

Writing in a standing chat is an ordinary chat turn, not a run: `load_standing_context()`
([standing_context.py](../../src/agent/standing_context.py)) builds a
`StandingContext` ([standing.py](../../src/agent/standing.py)) with the chat's goals
(`resolve_standing_instructions()`, so the Daily Briefing's stock prompt comes from code)
and a plain description of its schedule, rendered as the `# This Chat: <name>` section by
`format_standing_section()` ([prompts.py](../../src/agent/prompts.py), text in
`prompt_texts/standing.py`). The turn binds the user's chat tools plus `kv_store`
defaulting to the job's `agent:<id>` namespace; the job's grants and the unattended
approval gate do not apply while the user is present. A pending approval from a run still
blocks sending (`prepare_turn` refuses with a validation error until it is resolved).
Eval: `agent_chat_remind_me`.

## Transient Failure Retries

Transient model errors (connection errors, timeouts, rate limits, 503s) are retried with exponential backoff and jitter **per model call** inside the graph chat node (`AGENT_MAX_RETRIES`, `AGENT_RETRY_BASE_DELAY_SECONDS`, `AGENT_RETRY_MAX_DELAY_SECONDS`). There is deliberately no whole-run retry: replaying a turn would re-execute non-idempotent tools (Todoist/Calendar writes, WhatsApp sends). See [Agent Graph](../architecture/agent-graph.md#chat-node-and-transient-error-retries).

## Budget Limits

A standing job can have a daily spending limit (`budget_usd`, set in the editor or by
`edit_standing_chat`; empty = none). Before a run, `job_spend_today` sums the job's own
unattended cost since local midnight (the user's turns in the chat don't count); over the
budget the run is skipped and recorded, not counted as a failure, until the next day.

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
    **Edit** (standing chats that are not built-in), **Cancel** (chat items).
  - Clicking the row opens the job's chat.
  - Pausing an agent's job disables it (`paused_reason='disabled'`), so the editor and
    the Daily Briefing's Settings toggle agree.
  - A Run is refused while the job waits for an approval or is over its daily budget. So
    are a resume and a `trigger_agent` run (`hold_reason` in `item_scheduler.py`).

### Sidebar Badge

The sidebar shows:
- Unread count badge (total new messages across agent conversations)
- Waiting indicator (pulsing dot when agents need approval)

## Creating a Standing Chat

### By talking (standing chats phase 3, Nov 2026)

In an ordinary chat, "be my cycling coach, check my Garmin every evening at 8 and ask how
I feel" calls `create_standing_chat` (`src/agent/tools/standing_create.py`):

- The first call previews it and creates nothing: name, instructions, the schedule in
  words, and each tool with what it lets a run do ("todoist (can change your Todoist)",
  "manage_memory (can edit your memories)", "garmin_connect (read only)"). The user
  sees the model's retelling, not the tool output, so the labels must be true.
- All tools (`*`) cannot be granted from a chat (a steered model could otherwise get
  a daily agent with every write level); the user widens it under Agents. Names and
  instructions have the API's length limits (`AGENT_NAME_MAX_CHARS`,
  `AGENT_INSTRUCTIONS_MAX_CHARS`).
- It files a `create_agent` [proposal](proposals.md): the card lists every setting and
  what each tool can change. **Create agent** (or a typed yes) makes the server create the
  standing chat and its job with exactly those settings, re-checked (a name taken
  meanwhile fails the card cleanly). A changed version is a new card.
- Refused in standing chats and in unattended runs; never bound in anonymous chats. Names
  are unique ignoring case, and a user has at most `STANDING_CHATS_MAX_PER_USER` standing
  chats. Each gets a daily budget of `STANDING_CREATE_BUDGET_USD` (shown in the preview).
- A one-off reminder or watcher stays with `schedule`; the two docstrings point at each
  other. Evals: `standing_create_preview`, `standing_vs_schedule`.

### From the Command Center

1. Click the robot icon in the sidebar or navigate to Command Center
2. Click "New Agent" (the chat header's edit button opens the same `JobEditor` for an
   existing one)
3. Fill in:
   - **Name**: Unique per user
   - **Description**: What it does
   - **Schedule**: Cron expression or preset (blank = on demand only)
   - **Timezone**: For schedule interpretation
   - **Instructions**: Goals and behavior (a built-in shows its stock prompt until edited)
   - **Tool Permissions**: Which integrations it may use, and for Todoist and Calendar
     whether it "Can change things without asking"
   - **Enabled**: Toggle to run on schedule or not (`paused_reason='disabled'`)

The standing chat's header has **Run now** (`handleStandingRun` -> `POST /api/jobs/<id>/run`);
the result arrives in the chat.

## Job-to-Job Handoff

A run can start another standing job using the `trigger_agent` tool (granted like any other
tool):

```python
@tool
def trigger_agent(agent_name: str, message: str = "Continue") -> str:
    """Trigger another autonomous agent to run."""
```

Cycles are prevented via the `trigger_chain` in the `JobContext` (job ids) - a run cannot
trigger a job that's already in the current chain, and the chain is capped at
`AGENT_MAX_TRIGGER_DEPTH`.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_APPROVAL_TTL_HOURS` | 24 | Hours until approval requests expire |
| `AGENT_EXECUTION_TIMEOUT_MINUTES` | 10 | Max execution time before considered stale |
| `AGENT_MAX_TRIGGER_DEPTH` | 3 | Maximum job-to-job trigger chain length (cycles are always blocked) |
| `AGENT_MAX_RETRIES` | 3 | Max retry attempts for transient failures |
| `AGENT_MODEL_SDK_MAX_RETRIES` | 1 | Retries inside the Gemini SDK per chat-model call; a model that is down falls back to the other tier |
| `AGENT_RETRY_BASE_DELAY_SECONDS` | 1.0 | Initial retry delay |
| `AGENT_RETRY_MAX_DELAY_SECONDS` | 30.0 | Maximum retry delay |
| `STANDING_CHATS_MAX_PER_USER` | 10 | Standing chats a user may have; guards against creating them in a loop |
| `STANDING_CREATE_BUDGET_USD` | 0.5 | Daily budget of a standing chat created by talking |
| `AGENT_MAX_TOOL_RETRIES` | 2 | Max consecutive tool errors before LLM is told to give up |

Runs also use existing configuration for:
- `GEMINI_API_KEY` - LLM access
- `DATABASE_PATH` - storage
- Integration credentials (Todoist, Calendar) if used

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

In E2E test mode, these endpoints control job state:

- `POST /test/set-jobs-overview` - Set the job list (`GET /api/jobs`) a test renders
- `POST /test/seed-agent` - Seed a real agent (standing chat + job)
- `POST /test/set-job` - Set a standing chat's editor data (`GET /api/jobs/<id>`)
- `POST /test/seed-agent-with-approval` - Seed a standing chat whose job awaits an approval

Backend tests: [test_standing_chats.py](../../tests/unit/test_standing_chats.py),
[test_run_context.py](../../tests/unit/test_run_context.py),
[test_routes_jobs.py](../../tests/integration/test_routes_jobs.py),
[test_routes_job_editor.py](../../tests/integration/test_routes_job_editor.py),
[test_migration_0082.py](../../tests/integration/test_migration_0082.py); frontend:
[job-editor.test.ts](../../web/tests/component/job-editor.test.ts),
[agents.spec.ts](../../web/tests/e2e/agents.spec.ts).

## Routing Race Condition Prevention

Switching quickly between the Command Center, the planner and chats is guarded by the
navigation token pattern: see [Components](../ui/components.md#routing-race-condition-prevention).

## Future Enhancements

- Goals, notice jobs and routines from repetition (TODO.md; need a design first)
- Inline approval display in standing chats
- Webhook triggers

## Key Files

- [run_context.py](../../src/agent/run_context.py) - `JobContext`, trigger message, run history, approval recording
- [item_runner.py](../../src/agent/item_runner.py) / [item_scheduler.py](../../src/agent/item_scheduler.py) - one run / the scheduler pass
- [routes/jobs.py](../../src/api/routes/jobs.py), [routes/approvals.py](../../src/api/routes/approvals.py) - REST endpoints
- [routes/agent_assist.py](../../src/api/routes/agent_assist.py) - AI assist endpoints, `_PROMPT_TOOL_DESCRIPTIONS`
- [models/standing_chats.py](../../src/db/models/standing_chats.py), [job_runs.py](../../src/db/models/job_runs.py), [proposals.py](../../src/db/models/proposals.py) - storage
- [dev_scheduler.py](../../src/agent/dev_scheduler.py) / [run_agent_scheduler.py](../../scripts/run_agent_scheduler.py) - scheduling
- [CommandCenter.ts](../../web/src/components/CommandCenter.ts), [JobEditor.ts](../../web/src/components/JobEditor.ts), [core/agents.ts](../../web/src/core/agents.ts) - UI

## See Also

- [Agent Tools](agent-tools.md) - tool table, permissions, adding a tool, K/V store, browser
- [Agent Graph](../architecture/agent-graph.md) - the loop every run goes through
- [Push Notifications](push-notifications.md) - how agents notify the user
- [WhatsApp](whatsapp.md) - WhatsApp notifications for agents
- [Scheduled Jobs](../architecture/scheduled-jobs.md) - production scheduling
