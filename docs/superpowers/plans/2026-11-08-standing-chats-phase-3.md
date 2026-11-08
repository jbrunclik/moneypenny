# Standing Chats Phase 3: One Job List, Created by Talking - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Command Center becomes one list of all jobs (light and standing) with each job's recent runs and next run. "Be my cycle coach..." creates a standing chat with a job, by talking. The agent facade from phase 2 goes.

**Architecture:**
- Part E: one jobs overview endpoint feeds a rebuilt Command Center page, and pause, resume and run work for every job.
- Part F: an ordinary chat gets a `create_standing_chat` tool with the preview-then-confirm gate. It is built on the same pending gate as `schedule` and `edit_standing_chat`.
- Part G: replaces the `/api/agents` facade, the `autonomous_agents` view and the synthetic `Agent` with job endpoints and a job run context, and moves the agent editor onto them. It also adds per-tool write toggles.

**Tech Stack:** Flask/APIFlask + Pydantic schemas, SQLite + yoyo, LangGraph tools, vanilla TS + Zustand, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-08-standing-chats-design.md` (phase 3, and the "audit trail of done and planned" learning). It also carries phase 2's folded Part C and leftovers (TODO.md "Standing chats phase 3"; `docs/superpowers/plans/2026-11-08-standing-chats-phase-2.md` rulings).

## Scope

In:
- **E: the job list.** One list of all jobs: run now, pause or resume, edit, cancel, approvals, each job's recent runs and upcoming run.
- **F: created by talking.** "Be my coach, check X every evening" in any chat proposes a standing chat with a job. It is created on the user's yes in a later turn, with the grants listed in the preview.
- **G: the facade goes.** Job endpoints, the editor on them with read/write toggles per tool, and the `autonomous_agents` view, agents API, `AgentMixin` and synthetic `Agent` removed. Tables and columns get job names.

Out, needing a design conversation first (each a spec one-liner with no design yet):
- goals ("a standing chat carries a goal, drafts a plan, checks in");
- notice jobs ("scans memory, calendar and Todoist, speaks only when worth flagging", including the Sunday week-ahead);
- routines from repetition ("do this every Monday" turning the last turn's steps into a job).

These get their own brainstorm after this plan ships (TODO entry).

Dropped from the folded Part C (Ruling): merging `is_agent` / `is_sports` / `is_language` into one column. It renames branches without removing any. Agents, sports and language keep their own areas and dashboards, so the three flags are three areas, not three special cases. Cost if wrong: a later rename.

## Global Constraints

- Production daily driver (4 users). The public repo carries no infra in docs or commits.
- The 3 production agents, their chats, histories, grants, approvals and the Daily Briefing's Settings toggle survive every part. The briefing keeps its stock prompt until edited.
- Standing chats never appear in the conversation list.
- Unattended runs never gain the user's full tools. Grants widen only on the user's explicit yes or an approval.
- Silent by default: one alert per failure streak (as shipped in phase 2).
- Consolidate: every part removes or redirects code and must not add per-mode branches. Dead code goes with its tests and docs.
- UI changes are tested on desktop and mobile (768px breakpoint). Keep the liquid glass look and uniform vertical rhythm. No suggestion chips.
- Migrations: check the highest number on `main` right before committing (0081 today).
- Gate before each commit: `make lint` plus `E2E_PORT=8041 caffeinate -i nice -n 10 make pre-commit` (exit code checked). Stage explicit paths. One fresh Opus review per part before its deploy. Report eval costs.
- Production reads: counts only, with consent (given for this work on Nov 8 2026; ask again in a new session).

## Review Focus

1. A paused agent resumed from the job list really runs again. The briefing paused there shows "off" in Settings, and turning it on in Settings shows it running in the list. Test: E2 `test_pause_resume_an_agent_job_keeps_settings_in_step`.
2. A light item in a trashed or archived chat doesn't show in the job list, and comes back when the chat is restored. Test: E1 `test_overview_lists_live_chats_only`.
3. "Be my coach" asked twice, or confirmed after the user said no and moved on, creates nothing. The preview's grants are exactly what gets created. Tests: F1 `test_create_needs_a_later_yes`, `test_expired_preview_creates_nothing`, `test_created_grants_match_the_preview`.
4. After Part G a job's approval still resumes it, and a pre-G approval (made under the old table names) can still be approved. Test: G1 `test_migration_0082_carries_runs_and_approvals`, G3 `test_pre_rename_approval_resumes_the_job`.
5. A job's Run while it is over budget or waiting for an approval is refused with a reason, not run (phase 2 leftover). Test: E2 `test_run_now_refused_over_budget_or_awaiting_approval`.

---

## Part E: The job list

### Task E1: The jobs overview

**Files:**
- Create: `src/api/routes/jobs.py`, `src/api/schemas/jobs.py`, `src/api/helpers/job_responses.py`
- Modify: `src/db/models/scheduled_items.py` (`list_all_items(user_id) -> list[ScheduledItem]`: light items and jobs in live chats, agent jobs included), `src/db/models/agent_executions.py` (`recent_runs(job_ids: list[str], per_job: int) -> dict[str, list[AgentExecution]]`, one query), `src/api/routes/__init__.py` (register)
- Test: `tests/integration/test_routes_jobs.py`

**Interfaces:**
- `GET /api/jobs` returns `JobsOverviewResponse`:
  - `jobs: list[JobResponse]`
  - `pending_approvals` (the existing `ApprovalRequestResponse`)
  - `stats` (the existing `StatsBlock` shape)
  - `total_unread`, `jobs_waiting`, `jobs_with_errors` (the sidebar badge)
- `JobResponse`:
  - Identity: `id`, `kind` (reminder, check_in, watcher, recurring), `standing: bool`, `area` (`agents`, `sports`, `language` or `chat`, from the chat's flags).
  - Labels: `title` (the standing chat's name for agent jobs, else the item's text, shortened), `conversation_id`, `conversation_title`.
  - Schedule: `when`, `ends` (`describe_when` / `describe_ends`), `next_run_at` (null for NEVER), `status`, `paused_reason`.
  - Attention: `system_type`, `editable` (agent jobs that are not built-in), `unread_count` (agent chats), `has_pending_approval`, `cost_7d_display`.
  - `recent_runs: list[JobRunResponse]`, with `status`, `trigger_type`, `started_at`, `error` (truncated to 160 chars) and at most 3 per job.
- Ordering: needs attention first (pending approval, paused for failures, last run failed), then soonest `next_run_at`, then title.

- [ ] Write tests:
  - `test_overview_lists_light_items_and_jobs`
  - `test_overview_lists_live_chats_only` (trashed and archived chats hidden, back on restore)
  - `test_agent_job_titled_with_its_chat`
  - `test_recent_runs_newest_three`
  - `test_needs_attention_first`
  - `test_counts_for_the_sidebar`
  - `test_never_run_jobs_have_no_next_run`
- [ ] FAIL, then implement, then PASS. Regenerate OpenAPI and types. Commit `feat(jobs): one overview of every job`.

### Task E2: Pause, resume and run for every job

**Files:**
- Modify: `src/api/routes/schedules.py` (pause and resume work on agent jobs too: pausing a standing job sets `paused_reason='disabled'` and resuming clears it, so the agent's enabled state and the briefing's Settings toggle read the same thing; DELETE of an agent job stays refused, and its chat is deleted from the editor), `src/agent/item_scheduler.py` (`run_job_now` refuses with `JobHeldError(reason)` when the job is over its daily budget or waiting for an approval, for manual and `agent_trigger` runs alike; the scheduler's `_job_held` shares the check)
- Test: `tests/integration/test_routes_schedules.py`, `tests/unit/test_item_scheduler.py`, `tests/unit/test_agent_tool_modules.py` (trigger_agent)

- [ ] Write tests:
  - `test_pause_resume_an_agent_job_keeps_settings_in_step` (pause via the route, then the agent reads disabled and the briefing status reads off; resume reverses both)
  - `test_run_now_refused_over_budget_or_awaiting_approval`
  - `test_trigger_agent_refused_over_budget`
  - `test_deleting_an_agent_job_still_refused`
- [ ] FAIL, then implement, then PASS. Commit `feat(jobs): pause, resume and run every job; runs respect budget and approvals`.

### Task E3: The Command Center as one job list; Part E ship

**Files:**
- Modify:
  - `web/src/components/CommandCenter.ts`: rebuilt around `JobsOverviewResponse`. Header unchanged (title, New agent, Refresh). Then the approvals section, the stats strip, and one `.jobs-list`. The separate agent cards, "From chats" lane and Recent Activity section go.
  - `web/src/core/agents.ts`: data from `jobs.overview()`; handlers for run, pause, resume, cancel and edit.
  - `web/src/api/jobs.ts` (new): `overview()`.
  - `web/src/sync/command-center-sync.ts`: counts from the overview.
  - `web/src/components/Sidebar.ts`: badge fields renamed.
  - `web/src/state/slices/agents.ts`: holds `JobsOverviewResponse`.
  - `web/src/styles/components/agents.css`: job row styles; the agent-card and lane styles that are now unused are removed.
- Remove: `GET /api/agents/command-center` (route, schema, `get_command_center_data`, its tests), replaced by `/api/jobs`.
- Test: `web/tests/component/command-center.test.ts` (rewritten), `web/tests/e2e/agents.spec.ts` (desktop and mobile), `web/tests/visual/agents.visual.ts` (darwin baselines locally; Linux via `/regen-baselines`)

**The row** (desktop; on mobile the actions wrap under the text, with the same order and rhythm):

```
[icon] Coach                                   ● failed   [Run] [Pause] [Edit]
       every day at 20:00 · next tomorrow 20:00 · 7d: 5 runs · $0.12
       ▸ Recent runs: today 20:00 failed (Garmin login expired) · yesterday ok · Fri ok
[icon] Check the school's job board           paused     [Resume] [Cancel]
       checks daily · until a teacher job is posted · in "Dog's tail"
```

- The icon comes from the area or kind (agent robot, sports, language, or item kind).
- The status chip shows waiting for approval, paused (after failing / by you), or failed. It shows nothing when all is fine.
- "Recent runs" is collapsed; a tap expands it.
- Clicking the row (not a button) opens the job's chat.
- Built-in jobs show "Built-in" and no Edit.
- Empty state: "Nothing scheduled yet" plus the New agent button (no suggestion chips).

- [ ] Write tests:
  - Component: `renders one row per job`, `attention first`, `run/pause/resume/cancel/edit call their handlers`, `row click opens the chat`, `built-in has no edit`, `recent runs expand`, `empty state`
  - E2E, desktop and mobile: `the list shows an agent job and a chat item`, `pause then resume an agent job`, `run an agent job`, `cancel a chat item`
- [ ] FAIL, then implement, then PASS. Update the visual baselines (darwin now, Linux via the regen workflow). Docs: `docs/features/agents.md` (Command Center section). Gate, commit. **Review (Opus), fix pass, deploy Part E.**

## Part F: Created by talking

### Task F1: `create_standing_chat`

**Files:**
- Create: `src/agent/tools/standing_create.py` (tool `create_standing_chat`), `tests/unit/test_standing_create.py`
- Modify: `src/agent/tools/__init__.py` (bound in ordinary, non-anonymous chats beside `schedule`; never in standing chats or runs), `src/agent/tools/agent_kv.py` (reserve `standing_create_pending`), `src/agent/tool_display.py` (metadata), `src/agent/prompt_texts/` (one line in the tools guidance: an ongoing role with its own schedule is a standing chat, a one-off check is `schedule`)

**Interfaces:**
- Arguments: `create_standing_chat(name, instructions, schedule, grants, fresh_context=True, confirm=False)`.
  - `schedule` is a cron string, or a phrase the tool turns into cron with `schedule_spec`'s builders (days plus time). An unsupported phrase is refused with an example.
  - `grants` must be grantable tools (the phase 2 rules, write levels included).
- Preview: name, instructions, schedule in words, and the tools with write access spelled out ("can change your Todoist"). The pending gate applies: the next user message answers, a preview left behind expires, and a same-request confirm is refused.
- Confirm creates the standing chat and its job (`create_agent`, until Part G replaces it) and returns the chat's link `#/conversations/<id>`. The job's first run is the next schedule slot.
- Limits: at most `STANDING_CHATS_MAX_PER_USER` (new config, default 10) standing jobs per user, which is separate from the 20 light items. The name must be unique.

- [ ] Write tests:
  - `test_create_needs_a_later_yes`
  - `test_expired_preview_creates_nothing`
  - `test_created_grants_match_the_preview`
  - `test_preview_spells_out_write_access`
  - `test_refused_in_standing_chats_and_runs`
  - `test_name_must_be_unique`
  - `test_cap_on_standing_chats`
  - `test_unsupported_schedule_phrase_refused`
- [ ] FAIL, then implement, then PASS.
- [ ] Evals:
  - `standing_create_preview`: "Buď můj cyklistický trenér, každý večer v 8 se podívej na Garmin a zeptej se, jak se cítím" previews and doesn't confirm.
  - `standing_vs_schedule`: "remind me tomorrow at 9" still uses `schedule`.
  - Report the cost.
- [ ] Config: `src/config.py`, `.env.example`, both `.env` files (prod with Jiri's OK). Docs. Gate, commit. **Review, fix pass, deploy Part F.**

## Part G: The facade goes

### Task G1: Job names in the schema

**Files:**
- Create: `migrations/0082_job_tables.py`, `tests/integration/test_migration_0082.py`
- Migration 0082:
  - Create `job_runs` (copy of `agent_executions` with `agent_id` renamed `item_id`) and `job_approvals` (copy of `agent_approval_requests`, `agent_id` renamed `item_id`), then drop the old tables. These are created fresh rather than renamed, so no FK points at the backup.
  - Rename `conversations.agent_id` to `job_id` and `users.daily_briefing_agent_id` to `daily_briefing_job_id`.
  - Drop the `autonomous_agents` view and `_autonomous_agents_0080`.
  - Re-state the FTS triggers that mention `is_agent` (unchanged in meaning).
  - Rollback restores both tables, the view and the column names. The backup table is not restored: the view's rollback path from 0080 rebuilds agents from the chats and jobs.
- [ ] Write `test_migration_0082_carries_runs_and_approvals`, `test_rollback_0082`, then FAIL, then implement, then PASS (this task's code changes are in G2-G3; commit with G3).

### Task G2: Job context and grants, no synthetic Agent

**Files:**
- Modify:
  - `src/agent/executor.py` becomes `src/agent/run_context.py`: `JobContext(item: ScheduledItem, user: User, name: str, trigger_chain: list[str])`, with `get/set/clear_job_context`.
  - `src/agent/permissions.py` and `src/agent/tools/permission_check.py`: read `JobContext.item.grants`.
  - `src/agent/tool_node.py`, `src/agent/tools/request_approval.py`, `trigger_agent.py`, `agent_kv.py` (namespace `agent:<job id>`, unchanged value), `memory.py`, `scheduling.py`, `standing_settings.py`.
  - `src/agent/item_runner.py`: builds a `JobContext`, with no `Agent`.
  - `src/agent/tools/__init__.py`: `get_tools_for_agent(agent)` becomes `tools_for_grants(grants: list[str] | None, user_id: str)`.
  - `src/agent/prompts.py` / `agent.py`: the run prompt's context from the job and its chat.
- Remove: `src/db/models/agent*.py` facade methods, `agent_rows.py`, the `Agent` dataclass, `resolve_agent_system_prompt`. The job runs and approvals mixins move to `src/db/models/job_runs.py` / `job_approvals.py` on the new tables.
- Test: the existing permission, gate, item runner and settings suites, moved to the new names (the behavior assertions unchanged); `test_no_agent_dataclass_left` (an import guard).

### Task G3: Job endpoints and the editor on them; Part G ship

**Files:**
- Create:
  - `src/db/models/standing_chats.py` (`create_standing_chat(user_id, name, instructions, schedule, timezone, grants, model, budget_usd, fresh_context, standing_type=None) -> ScheduledItem`, `update_standing_chat(job_id, user_id, **changes)`, `delete_standing_chat(job_id, user_id)`; this replaces `create/update/delete_agent`)
  - Routes in `src/api/routes/jobs.py`: `POST /api/jobs` (create a standing chat with its job), `GET/PATCH/DELETE /api/jobs/<id>`, `GET /api/jobs/<id>/runs`, `POST /api/jobs/<id>/run`, and approvals at `/api/approvals/...` (moved from `agent_approvals.py`).
- Modify: `web/src/components/AgentEditor.ts` (renamed `JobEditor.ts`; the same form on the job endpoints, plus a per-tool **"can change things"** toggle for `WRITE_LEVEL_TOOLS`, which shows and edits write levels), `web/src/api/agents.ts` (renamed `api/jobs.ts`), the conversation header (Edit, plus **Run** for standing chats), `daily_briefing.py`, `standing_create.py` (on `create_standing_chat`), `evals/run.py`
- Remove: `src/api/routes/agents.py`, `agent_approvals.py`, `agent_command_center.py` leftovers, `src/api/schemas/agents.py` (what the new routes still need moves to `schemas/jobs.py`), `agent_responses.py`, the frontend agent-only types.
- Keep: `/api/ai-assist/parse-schedule` and `enhance-prompt` (the editor still uses them).
- Test:
  - `tests/integration/test_routes_jobs.py` (CRUD, run, runs, `test_pre_rename_approval_resumes_the_job`, `test_editor_save_keeps_write_levels`, `test_write_toggle_sets_and_clears_the_level`)
  - `web/tests/component/job-editor.test.ts` (moved, plus the write toggle)
  - E2E: agents spec on the new endpoints, desktop and mobile
- [ ] Gate. Count the removed lines and branches for the report. Docs: `docs/features/agents.md` rewritten as "Standing chats and jobs"; `docs/architecture/scheduled-jobs.md`, `docs/features/push-notifications.md` and the other mentions. TODO: the phase 3 entry replaced by the goals/notices/routines design item. **Review (Opus), fix pass, deploy Part G.** Production check: counts only.

## Rulings made while planning

- Ruling: phase 3 is split. E/F/G are designed by the spec; goals, notices and routines-from-repetition are one-liners and get a design conversation first. Cost if wrong: they ship one round later.
- Ruling: the `is_agent`/`is_sports`/`is_language` merge is dropped (three real areas, not special cases). Cost if wrong: a later rename.
- Ruling: pausing an agent job from the list uses `paused_reason='disabled'`, so the Agents editor, the view (until G) and the briefing's Settings toggle agree. Cost if wrong: one more pause reason later.
- Ruling: Part G creates `job_runs`/`job_approvals` fresh instead of renaming, so no foreign key can point at the dropped backup. Cost if wrong: a slightly longer migration.
- Ruling: `STANDING_CHATS_MAX_PER_USER` defaults to 10 (the spec's standing jobs have no count limit, but talking makes creation cheap; the cap is a guard against a runaway loop, not a product limit). Cost if wrong: one config change.
