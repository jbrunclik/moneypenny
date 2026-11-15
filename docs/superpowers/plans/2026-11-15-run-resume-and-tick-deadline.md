# Run Resume and Tick Deadline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An approved run continuation survives a deploy, and a scheduler pass never runs past systemd's kill.

**Architecture:** Approval stores the continuation on the job's `scheduled_items` row; the next scheduler pass claims and runs it. The pass gets a deadline; each model run gets a time budget capped by it, carried in the graph state so the turn budget stops the run cleanly.

**Tech Stack:** Python, SQLite (yoyo migrations), LangGraph.

**Spec:** docs/superpowers/specs/2026-11-15-run-resume-and-tick-deadline-design.md

## Global Constraints

- `SCHEDULE_TICK_DEADLINE_SECONDS` = 270, `SCHEDULE_RUN_FINISH_MARGIN_SECONDS` = 90, `SCHEDULE_MIN_RUN_SECONDS` = 60 (src/config.py with units, `.env.example`, docs); `SCHEDULE_TICK_BUDGET_SECONDS` is removed.
- Card text after approval: "Approved - continuing shortly."
- No new process; "Run now" (`run_job_now` by hand) unchanged.
- Gate per task: `make lint` + `make test` (backend only); TDD; commit by explicit paths.

## Review Focus

- A resume whose job or user was deleted meanwhile: cleared, no crash, no retry loop (Task 3 test).
- A resume for a job that now has another pending card or is over budget: held, message kept, runs once released (Task 3 test).
- A resume for a paused (disabled) job: still runs, like `run_job_now` today, and the job stays paused (Task 3 test).
- A pass with one-offs after the deadline: reminders still fire (no model call) (Task 2 test).
- A run not started for lack of time: item given back unchanged, no failure counted (Task 2 test).

---

### Task 1: A per-run time budget in the turn budget

**Files:**
- Modify: `src/agent/turn_budget.py` (`initial_state`, `budget_stop`, `wrap_up_due`, `stop_facts`), `src/agent/graph_state.py` (AgentState)
- Test: `tests/unit/test_turn_budget_run_limit.py`

**Interfaces:**
- Produces: `run_time_budget(seconds: float) -> ContextManager[None]` and `time_budget_s(state: AgentState) -> float` in `turn_budget.py`; AgentState key `turn_time_budget_s: float`.

- [ ] Step 1: tests - `initial_state([])["turn_time_budget_s"] == Config.TURN_TIME_BUDGET_SECONDS`; inside `with run_time_budget(30):` it is 30; `budget_stop` returns "time" when elapsed ≥ the state's limit (30) though below the global 240; `wrap_up_due` uses the state's limit; `stop_facts("time", ...)` names "the 30 s time limit".
- [ ] Step 2: run, expect FAIL (no `run_time_budget`).
- [ ] Step 3: implement with a ContextVar read by `initial_state` (the agent calls it in the pass's thread; nodes read the state, not the var). A state without the key uses the global.
- [ ] Step 4: tests pass; `make lint`, `make test`.
- [ ] Step 5: commit `feat(agent): a run's time budget can be capped below the turn default`.

### Task 2: The pass deadline

**Files:**
- Modify: `src/agent/item_scheduler.py` (`run_due_items`), `src/config.py`, `.env.example`, `docs/features/scheduled-items.md`, `docs/architecture/scheduled-jobs.md`; local and production `.env` (both carry `SCHEDULE_TICK_BUDGET_SECONDS=240`: remove it, add the three new keys at their defaults, line-for-line with `.env.example` - only with the user's OK, back up outside the repo first, restart the service after the production edit)
- Test: `tests/unit/test_item_scheduler.py` (new tests)

**Interfaces:**
- Consumes: `run_time_budget` (Task 1).
- Produces: `_run_budget_s(started: float, now_mono: float) -> float | None` in `item_scheduler.py` (None = too little left).

- [ ] Step 1: tests (patch `_monotonic`) - at 0 s elapsed a model run gets 180 (270 - 90, under the 240 default); at 100 s it gets 80 and the run sees `turn_time_budget_s == 80`; at 150 s 270 - 150 - 90 = 30 < 60, so it is not started: the item is given back with `next_run_at` and `failures` unchanged; a reminder due after the deadline still fires.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement; wrap `_handle`'s model run in `run_time_budget(budget)`; log "Run budget capped by the scheduler pass" (item_id, budget_s) when below the default; remove `SCHEDULE_TICK_BUDGET_SECONDS` (config, `.env.example`, docs, `tests/unit/test_item_scheduler.py:394`).
- [ ] Step 4: tests pass; lint, test.
- [ ] Step 5: commit `fix(scheduler): a pass never outlives systemd; runs near its end stop on time`.

### Task 3: Durable resume after cards

**Files:**
- Create: `migrations/0092_scheduled_items_resume_message.py` (number: highest on main + 1 at commit time)
- Modify: `src/db/models/dataclasses.py` (ScheduledItem `resume_message: str | None = None`), `src/db/models/scheduled_items.py` (`row_to_item`, `claim_due_items`, new `request_resume`, `clear_resume`), `src/agent/run_approvals.py` (`_settle`, `apply_agent_action`, remove `_resume` thread), `src/agent/item_scheduler.py` (`_handle`)
- Test: `tests/unit/test_run_resume.py`; update `tests/unit/test_run_approvals.py` where it expects a thread or "Approved - continuing."

**Interfaces:**
- Produces: `Database.request_resume(item_id: str, message: str) -> bool`, `Database.clear_resume(item_id: str) -> None`.

- [ ] Step 1: tests -
  - approving the last card stores the outcome on the item (`resume_message` contains "[Action approved:" and "Re-issue exactly:"), starts no thread, returns "Approved - continuing shortly.";
  - a pass claims an active item with a `resume_message` though `next_run_at` is in the future, runs `run_model_item(trigger="approval", message=<it>)`, delivers with push, then the item has no `resume_message` and its `next_run_at` is unchanged;
  - a paused (disabled) job's resume runs and the job stays paused;
  - held (another pending card) → not run, message kept;
  - job deleted before the pass → nothing runs, no error;
  - a run that raises → failure counted, message kept;
  - "Run resumed after cards" logged with `waited_s`.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement. Claim: `status IN ('active','paused') AND resume_message IS NOT NULL` or the due condition; remember the prior status to restore. In `_handle` a resume runs before (instead of) a due run, inside the pass deadline (Task 2), and gives the item back via `release_item` (schedule unchanged) then `clear_resume`.
- [ ] Step 4: tests pass; lint, test.
- [ ] Step 5: docs (`docs/features/agents.md` approval steps, `docs/features/proposals.md`), review check in `docs/regular-review.md`, TODO: remove the two audit lines, add "Re-measure run resumes and capped runs (~Dec 15 2026)"; commit `fix(agents): an approved run continues from the scheduler, surviving deploys`.
