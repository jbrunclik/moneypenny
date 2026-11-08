# Standing Chats Phase 2: Jobs Carry Grants - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scheduled items gain grants, approvals, budget and model ("standing jobs"); the three production agents become standing chats with a standing job (histories kept); the autonomous-agents subsystem goes; agents edit their own settings with approval.

**Architecture:** A standing job is a `scheduled_items` row with `grants` set. Its run reuses today's unattended machinery: the item runner builds the synthetic `Agent` it already builds, so `AgentContext`, `check_autonomous_permission`, the tool node's autonomous split, `request_approval` and `trigger_agent` work unchanged until Part C renames them. A migrated agent's job keeps the agent's id, so every existing reference stays valid: `conversations.agent_id`, `agent_executions.agent_id`, `agent_approval_requests.agent_id`, `users.daily_briefing_agent_id` and frontend links. The chat's standing instructions move from `autonomous_agents` to columns on `conversations`.

**Tech Stack:** Flask, LangGraph `ChatAgent`, SQLite + yoyo, croniter, pytest, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-08-standing-chats-design.md` (phase 2; the limits table; "Agents edit their own settings"; the Learnings bullets marked phase 2).

## Shipping

Phase 2 ships as four deploys, each green and deployed on its own (Ruling: one phase-2 deploy would be a ~9k-line change that also migrates production data; four parts keep every deploy revertable):

- **Part A**: standing jobs exist. Additive only; nothing creates them yet except tests.
- **Part B**: the agents migrate. The one data migration, and the code switches to jobs.
- **Part C**: the agent system goes. Tables, code, tests and docs are removed, and `is_agent`/`is_sports`/`is_language` become one column.
- **Part D**: settings edits with approval, "always allow", per-connector grant levels and drafts.

## Global Constraints

- Production daily driver (4 users). The repo is public: no infra in docs or commits.
- Three production agents survive with their histories, schedules, budgets, grants, unread state, and pending approvals: Daily Briefing, VWCE Watcher, the cycle coach. Program chats and their kv state are untouched.
- The planner is out of scope.
- Unattended runs never gain the user's full tools. Writes still need approval. An agent never widens its own grants.
- Standing chats never appear in the conversation list.
- Silent by default: one alert per failure streak, never one per failed run.
- Consolidate: every task removes or redirects branches and must not add a per-mode one. Dead code goes with its tests and docs.
- Migrations: check the highest number on `main` right before committing. Today's is 0077.
- New env vars go in `src/config.py` (with a default), `.env.example`, both `.env` files (prod flips need Jiri's OK), and a `docs/features/` page.
- Gate before each commit: `make lint` plus the full suite (`E2E_PORT=8041 caffeinate -i nice -n 10 make pre-commit`, exit code checked). Stage explicit paths. Deploy after each Part. Report eval costs.
- Production check after Part B: counts only (3 jobs with grants, 0 agents still scheduled), with Jiri's consent for the read.

## Review Focus

1. The Daily Briefing still runs at 07:15 local time with the stock prompt from code, and its Settings toggle still turns it on and off after the migration. Tests: B2 `test_briefing_job_keeps_stock_prompt`, B4 `test_settings_toggle_creates_chat_and_job`.
2. A pending approval created before the migration can still be approved after it, the run resumes, and the one destructive call goes through exactly once. Test: B3 `test_pre_migration_approval_resumes_the_job`.
3. A user's own long chat with the coach doesn't use up the coach's daily budget, and the job's runs do. Tests: A2 `test_budget_counts_job_runs_only`, A3 `test_over_budget_skips_without_counting_a_failure`.
4. A standing job that fails 3 times pauses: one alert message with a Resume action, no further runs, and the job, chat and grants all stay. A light item still stops and is deleted, as shipped. Test: A3 `test_standing_job_pauses_after_failures_with_one_alert`.
5. A run in the coach chat still can't widen its own grants. A settings change proposed during a run waits for approval, and one proposed in conversation waits for the user's yes in a later turn. Tests: D1 `test_unattended_settings_change_files_approval`, `test_chat_settings_change_needs_later_yes`, `test_grants_never_widen_without_approval`.

---

## Part A: Standing jobs

### Task A1: Standing columns and their model

**Files:**
- Create: `migrations/0078_standing_jobs.py`, `tests/integration/test_migration_0078_rollback.py`
- Modify: `src/db/models/dataclasses.py` (`ScheduledItem`), `src/db/models/scheduled_items.py`, `src/db/models/cost.py`, `src/services/costs.py` (`calculate_and_save_message_cost` gains `job_id: str | None = None`)
- Test: `tests/integration/test_db_scheduled_items.py`

**Interfaces:**
- Migration 0078:
  - `scheduled_items` gains:
    - `grants TEXT`: NULL means a light item. Otherwise a JSON list of tool names, or `["*"]` for all tools, matching what `tool_permissions` means today.
    - `model TEXT`, `budget_usd REAL`
    - `fresh_context INTEGER NOT NULL DEFAULT 1`
    - `timezone TEXT`: the cron is evaluated in this zone, defaulting to `APP_TIMEZONE`.
    - `paused_reason TEXT`
  - `message_costs` gains `job_id TEXT` with index `(job_id, created_at)`.
  - Rollback drops all of these.
- `ScheduledItem` gains the same fields plus a property `standing: bool` (`grants is not None`).
- `count_items(user)` counts light items only. Standing jobs don't use up the 20.
- `set_item_paused(item_id, user_id, paused, reason=None)` stores or clears `paused_reason`.
- `job_spend_today(job_id) -> float`: SUM of `message_costs.cost_usd` where `job_id = ?` since `local_day_start`.

- [ ] Write tests: `test_standing_fields_round_trip`, `test_standing_jobs_do_not_count_toward_the_cap`, `test_job_spend_today_counts_only_that_job` (a user turn's cost row in the same chat, `job_id` NULL, is excluded), `test_pause_reason_is_kept_and_cleared`, and the migration rollback test.
- [ ] Run, expect FAIL. Implement. Run, expect PASS. Commit `feat(jobs): standing job columns - grants, model, budget, timezone`.

### Task A2: One run path for light items and standing jobs

**Files:**
- Modify: `src/agent/item_runner.py`, `src/agent/tools/__init__.py` (rename `get_tools_for_agent(agent)` to `tools_for_grants(grants: list[str] | None)`; callers pass `agent.tool_permissions` until Part C), `src/agent/executor.py` (the shared pieces `item_runner` now calls: `_set_run_context`, `_run_history`, `_record_approval_request`)
- Test: `tests/unit/test_item_runner.py`

**Interfaces:**
- `run_model_item(item, *, trigger: Literal["scheduled", "manual", "job_trigger"] = "scheduled", message: str | None = None) -> ItemOutcome`, with the same outcome type as today.
- Light item, unchanged: web-only tools, no memories, fresh context, `DEFAULT_MODEL`. In a standing chat it also sees that chat's standing context (instructions and state, via `load_standing_context`). Ruling: the spec says "light items in ordinary chats stay context-free"; items in standing chats get the context.
- Standing job:
  - Tools are `tools_for_grants(item.grants)`. Memories are passed only when `manage_memory` is granted or the grants are `["*"]`.
  - Model is `item.model or DEFAULT_MODEL`. History is the chat's compacted history unless `fresh_context`.
  - It gets the chat's standing context, and the job's `text` is the run's task line.
  - The synthetic `Agent` carries id = `item.id`, `tool_permissions = item.grants`, model, `fresh_context`, `budget_limit`.
  - It records an `agent_executions` row (`agent_id = item.id`, the trigger type), and its cost rows carry `job_id = item.id`.
  - An approval request is recorded and pushed as agent approvals are today, with `agent_id = item.id`.
- Push on delivery: `"{chat name}"` plus the first line, tag `job-{id}`.

- [ ] Write tests:
  - `test_light_item_in_ordinary_chat_is_context_free`
  - `test_light_item_in_standing_chat_sees_its_instructions`
  - `test_standing_job_gets_its_grants_not_full_tools`
  - `test_standing_job_memory_only_when_granted`
  - `test_standing_job_uses_history_unless_fresh`
  - `test_standing_job_cost_rows_carry_job_id`
  - `test_budget_counts_job_runs_only`
  - `test_standing_job_approval_request_is_recorded_and_pushed`
  - `test_standing_job_records_an_execution`
- [ ] FAIL, then implement, then PASS. Commit `feat(jobs): standing jobs run with their grants and the chat's context`.

### Task A3: Standing-job limits in the scheduler

**Files:**
- Modify: `src/agent/item_scheduler.py`, `src/utils/schedule_spec.py` (a standing job accepts any valid cron, validated with croniter)
- Test: `tests/unit/test_item_scheduler.py`

**Interfaces:** for a standing job:
- No expiry, and no slowdown.
- `_next_run` evaluates the cron in `item.timezone`.
- Over budget: skip the run. A failed execution is recorded with "over daily budget", but it doesn't count as a failure. The next run is scheduled, and nothing is delivered.
- After `SCHEDULE_ITEM_MAX_FAILURES`, set `status='paused'` and `paused_reason='failures'`. One alert message is delivered (`delivery.kind="alert"`, text "Paused after 3 failed runs: <last error, 160 chars>. Resume it from the chat's schedule chip.") with one push. The item is not deleted.
- Resume (existing route) clears `paused_reason` and `failures`.

- [ ] Write tests:
  - `test_standing_job_has_no_expiry_or_slowdown`
  - `test_standing_job_cron_runs_in_its_timezone`
  - `test_any_cron_for_standing_hourly_ok`
  - `test_over_budget_skips_without_counting_a_failure`
  - `test_standing_job_pauses_after_failures_with_one_alert`
  - `test_resume_clears_failures_and_reason`
  - `test_light_item_still_stops_after_failures` (regression)
- [ ] FAIL, then implement, then PASS. Commit `feat(jobs): standing job limits - pause with one alert, budget, any cron`.

### Task A4: Approvals and runs for jobs; Part A ship

**Files:**
- Modify: `src/api/routes/agent_approvals.py` (approve: when `agent_id` names a standing job, resume through `run_model_item(item, trigger="manual")`), `src/api/routes/schedules.py` (`POST /api/schedules/<id>/run` for standing jobs; 409 for light items, or while running or awaiting approval), `src/api/schemas/schedules.py` (`ScheduledItemResponse` gains `standing`, `paused_reason`), regenerated OpenAPI/types, `web/src/components/ScheduleIndicator.ts` (paused-by-failures text; Run for standing jobs)
- Test: `tests/integration/test_routes_agent_approvals.py`, `tests/integration/test_routes_schedules.py`, `web/tests/unit/schedule-indicator.test.ts`, `web/tests/e2e/scheduled-items.spec.ts` (desktop and mobile)

- [ ] Write tests:
  - `test_approving_a_job_request_resumes_the_job`
  - `test_run_now_standing_job`
  - `test_run_now_refused_for_light_items`
  - `test_chip_shows_paused_after_failures`
  - E2E: a seeded standing job shows Run and its paused reason
- [ ] FAIL, then implement, then PASS. Gate, commit `feat(jobs): approve, resume and run standing jobs`. **Deploy Part A.**

## Part B: The agents migrate

### Task B1: Standing instructions on the chat

**Files:**
- Create: `migrations/0079_standing_chat_columns.py`
- Modify: `src/db/models/dataclasses.py` (`Conversation`), `src/db/models/conversation_rows.py`, `src/db/models/conversation.py` (`set_standing(conv_id, name, instructions, standing_type)`), `src/api/helpers/standing_context.py` (agent kind reads the conversation's columns), `src/agent/daily_briefing.py` (`resolve_standing_instructions(conv) -> str`: the stored instructions, or the stock prompt for `standing_type`)
- Test: `tests/unit/test_standing_context.py`, `tests/unit/test_daily_briefing.py`

**Interfaces:** `conversations` gains:
- `standing_name TEXT`
- `standing_instructions TEXT`: NULL with a `standing_type` means the stock prompt from code. The first edit stores a copy, as `system_prompt` works today.
- `standing_type TEXT`: `daily_briefing` or NULL.

- [ ] Write tests: `test_agent_chat_instructions_come_from_the_chat`, `test_briefing_chat_uses_stock_prompt_until_edited`. FAIL, then implement, then PASS. Commit.

### Task B2: The data migration

**Files:**
- Create: `migrations/0080_agents_to_standing_jobs.py`, `tests/integration/test_migration_0080.py`

**Interfaces:** for each `autonomous_agents` row:
- **Conversation:** `standing_name = name`, `standing_instructions = system_prompt`, `standing_type = system_type`. `is_agent` and `agent_id` stay; `agent_id` now names the job.
- **Job:** insert a `scheduled_items` row with:
  - `id = agent.id`, `user_id`, `conversation_id`, `kind='recurring'`
  - `text = 'Do what this chat's standing instructions describe.'`
  - `schedule = agent.schedule`, `timezone = agent.timezone`, `next_run_at = agent.next_run_at` (or now when NULL)
  - `grants = tool_permissions` (`'["*"]'` when NULL), `model`, `budget_usd = budget_limit`, `fresh_context`
  - `status = 'active'` if enabled, else `'paused'` with `paused_reason='disabled'`
- **Old agent row:** `enabled=0` and `next_run_at=NULL`, so the old scheduler path, still present until C, can never fire it. The row is kept for rollback.
- **Rollback:** delete the inserted items, clear the conversation columns, restore `enabled` and `next_run_at` (stored in a backup table `_0080_agent_state` that the rollback drops).

- [ ] Write tests:
  - `test_each_agent_becomes_a_job_with_the_same_id`
  - `test_unrestricted_agent_gets_all_grant`
  - `test_disabled_agent_job_is_paused`
  - `test_briefing_job_keeps_stock_prompt`
  - `test_old_rows_no_longer_scheduled`
  - `test_rollback_restores_agents`
- [ ] FAIL, then implement, then PASS. Commit.

### Task B3: The code switches to jobs

**Files:**
- Modify:
  - `src/agent/scheduler.py`: drop `get_due_agents` and `_run_due_agent`. One pass: zombies, then `run_due_items`.
  - `src/agent/tools/trigger_agent.py`: the target is a standing job, found by its chat's `standing_name`, keeping chain and depth protection.
  - `src/api/routes/agents.py`: list, get, patch, delete, run and executions become a facade over chat + job, keeping the HTTP shapes, so the Command Center, editor and header are unchanged until phase 3.
  - `src/db/models/agent_stats.py`: Command Center data and stats from jobs and executions.
  - `src/api/routes/agent_approvals.py`: always resumes through the job.
  - `src/agent/tools/agent_kv.py`: namespace `agent:<job id>`, unchanged in value.
- Test: `tests/integration/test_routes_agents.py`, `tests/integration/test_routes_agent_command_center.py`, `tests/integration/test_routes_agent_approvals.py`, `tests/unit/test_scheduler.py`, `tests/unit/test_tools.py` (trigger_agent)

- [ ] Write tests:
  - `test_agents_api_lists_standing_jobs_in_the_old_shape`
  - `test_edit_agent_updates_chat_and_job`
  - `test_run_agent_runs_the_job`
  - `test_pre_migration_approval_resumes_the_job`
  - `test_trigger_agent_reaches_a_standing_job_by_name`
  - `test_scheduler_runs_jobs_only`
- [ ] FAIL, then implement, then PASS. Commit.

### Task B4: Daily Briefing and agent creation make chat + job; Part B ship

**Files:**
- Modify: `src/agent/daily_briefing.py` (`set_briefing` creates or updates a standing chat with `standing_type='daily_briefing'` and a job at 07:15 with `["*"]` grants and fresh context), the create path behind `POST /api/agents`, `docs/features/agents.md`
- Test: `tests/unit/test_daily_briefing.py`, `tests/integration/test_routes_settings.py`, `web/tests/e2e/agents.spec.ts` (still green, desktop and mobile)

- [ ] Write tests: `test_settings_toggle_creates_chat_and_job`, `test_toggle_off_pauses_the_job`, `test_create_agent_makes_chat_and_job`. FAIL, then implement, then PASS.
- [ ] Gate. Eval run for the agent cases (report cost). Commit. **Deploy Part B.** Production check: counts only, with consent.

## Part C: The agent system goes

### Task C1: One conversation column for the standing area

**Files:**
- Create: `migrations/0081_standing_area.py` (`conversations.standing_area TEXT` in `agents|sports|language|NULL`, backfilled from `is_agent` / `is_sports` / `is_language`; the old columns are dropped; FTS triggers re-stated to exclude `standing_area='agents'`, as 0067 does with `is_agent`)
- Modify: every `is_agent` / `is_sports` / `is_language` branch the inventory lists (backend listing, archive, trash, sync, costs, conversation search, standing context; frontend `types/api.ts`, conversation switch, deeplink, initial route, remote merge, sync, sidebar). Sports and language keep their dashboards. Only the flag changes.
- Test: the existing suites for each touched module, plus `test_migration_0081` (backfill and FTS exclusion)

- [ ] Write `test_migration_0081` and update the touched tests to the new field. FAIL, then implement, then PASS. Gate, commit.

### Task C2: Remove the agent tables and their code

**Files:**
- Create: `migrations/0082_drop_agent_tables.py`. Rename `agent_executions` to `job_runs` (`agent_id` becomes `item_id`) and `agent_approval_requests` to `approval_requests` (`agent_id` becomes `item_id`). Rename `users.daily_briefing_agent_id` to `daily_briefing_job_id` and `conversations.agent_id` to `job_id`. Drop `autonomous_agents` and `_0080_agent_state`.
- Delete:
  - `src/db/models/agent.py`, `agent_schedule.py`, `agent_conversation.py`, `agent_rows.py`. The execution and approval mixins are renamed to job runs and approvals.
  - The executor's agent-only paths (`execute_agent`, `AgentExecutor`, `_load_run_conversation`, `_build_trigger_message` move into `item_runner` where still used).
  - `src/agent/prompt_agents.py` if unused after A2.
  - `src/api/routes/agent_assist.py` only if the editor no longer calls it. It stays while the form editor does (phase 3 keeps the form for fine-tuning).
  - Dead streaming approval handling (`stream_producer._report_approval_request`, `stream_consumer`, `stream_finalize._finalize_approval_stream`, frontend `approval_required`), after confirming no chat turn can raise it.
  - The synthetic `Agent`. `AgentContext` becomes `JobContext(item, user, trigger_chain)`, and `check_autonomous_permission` and `tool_node` read the job's grants.
- Tests: delete the agent-only test files from the inventory, move their still-valid cases to the job tests, and update the fixtures (`tests/conftest.py`, `tests/e2e_server/*`).
- Docs: `docs/features/agents.md` is rewritten as "Standing chats and jobs". `docs/architecture/scheduled-jobs.md` and the other pages from the inventory are updated.

- [ ] Write `test_migration_0082` (data carried: runs, approvals, briefing pointer, chat job ids). Run the whole suite red, then work through until green. Gate, commit.
- [ ] Count the removed lines and branches for the report. **Deploy Part C.** Production check: counts only.

## Part D: Settings, approvals and grant levels

### Task D1: Agents edit their own settings, with approval

**Files:**
- Create: `src/agent/tools/standing_settings.py` (tool `edit_standing_chat`), `tests/unit/test_standing_settings.py`
- Modify: `src/agent/tools/__init__.py` (bound in standing chats with a job, and in standing runs), `src/agent/tools/agent_kv.py` (reserve `standing_pending`), `src/agent/prompt_texts/standing.py` (the read-only-when-absent rule)

**Interfaces:**
- Fields: `instructions`, `schedule`, `model`, `budget_usd`, `fresh_context`, `grants`.
- In conversation: `edit_standing_chat(changes)` returns PREVIEW. `edit_standing_chat(confirm=true)` in a later user turn applies it. This is the schedule tool's gate, with the same pending-state rules: kv `standing_pending`, newer user message, same request refused.
- In an unattended run: files an approval request (`tool_name='edit_standing_chat'`, args = the changes). The change applies only when the user approves.
- Grants in a change always need the explicit yes or approval, never anything implied.
- A briefing's first instructions edit stores the copy.

- [ ] Write tests:
  - `test_chat_settings_change_needs_later_yes`
  - `test_same_turn_confirm_refused`
  - `test_unattended_settings_change_files_approval`
  - `test_grants_never_widen_without_approval`
  - `test_briefing_edit_freezes_a_copy`
  - `test_pending_namespace_is_reserved`
- [ ] FAIL, then implement, then PASS. Eval cases (`standing_settings_preview`, `standing_settings_unattended`), report the cost. Gate, commit.

### Task D2: Allow once, deny, always allow

**Files:**
- Modify: `src/api/routes/agent_approvals.py` (becomes `approvals.py` after C), with `POST /api/approvals/<id>/approve` taking `always: bool` (adds the tool to the job's grants, e.g. `todoist:write`; never for `edit_standing_chat` grants changes); `web/src/components/messages/render.ts` (a third button "Always allow"), regenerated types
- Test: `tests/integration/test_routes_approvals.py`, `web/tests/component/Messages.test.ts`, the E2E approval flow (desktop and mobile)

- [ ] Write tests: `test_always_allow_adds_the_grant`, `test_always_allow_refused_for_grant_changes`, a component test for the three buttons. FAIL, then implement, then PASS. Gate, commit.

### Task D3: Per-connector levels and drafts by default; Part D ship

**Files:**
- Modify: `src/agent/permissions.py` / `tools/permission_check.py`. A grant is `<integration>` (read) or `<integration>:write`, for `todoist`, `calendar`, `whatsapp`, `gmail` where present. A write op without the `:write` grant becomes an approval request (the "draft"), instead of being blocked. A migration maps existing tool-name grants: a tool name means `:write` for the agents that have it today, so behavior is unchanged for them.
- Test: `tests/unit/test_destructive_approval_gate.py` (moves to the job tests in C), `test_write_without_write_grant_files_approval`, `test_read_grant_allows_reads_only`, `test_existing_grants_keep_their_behavior`

- [ ] FAIL, then implement, then PASS. Gate, commit, update the docs. **Deploy Part D.**

## Rulings made while planning

- Ruling: four deploys instead of one, so each deploy is revertable and only Part B touches production data. Cost if wrong: four gate runs instead of one.
- Ruling: the job keeps the agent's id. No reference rewrites, the frontend is unchanged through Part B, and rollback is trivial. Cost if wrong: an `agent_id` column briefly names a job, until Part C renames it.
- Ruling: Part B keeps the `/api/agents` HTTP shape as a facade over jobs, because phase 3 rebuilds the Command Center as the job list and removes the facade then. Cost if wrong: one interim facade module.
- Ruling: grants keep today's tool-name meaning until D3 adds levels, so the migration is 1:1. Cost if wrong: D3 carries a small grants migration.
- Ruling: a standing job over its daily budget skips the run and doesn't count it as a failure (the spec is silent). Cost if wrong: a job silently skipping all day. The skipped execution row shows in run history.
