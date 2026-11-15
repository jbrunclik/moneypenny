# Approved runs survive deploys; the scheduler pass never outlives systemd

Date: 2026-11-15. Size: small change. Status: approved approach (A), design for review.

## Why

Peace of mind (the user's words) before agents do more. The Nov 15 2026 audit
found two holes; neither has happened yet (0 run cards ever, longest run 102 s of
142 in 60 days, no scheduler timeout in the journal since Oct 18). Invite cards
(Nov 15) make run approvals real soon.

1. **An approved action can vanish.** `run_approvals._resume` continues the run on
   a daemon thread in the web worker; a deploy or worker recycle kills it while
   the card says "Approved - continuing".
2. **The scheduler pass can be killed mid-run.** systemd kills the pass at 300 s
   (`TimeoutStartSec`); the pass starts runs for up to `SCHEDULE_TICK_BUDGET_SECONDS`
   (240) and one run may take `TURN_TIME_BUDGET_SECONDS` (240). A killed run's item
   is freed after `SCHEDULE_RUN_STALE_MINUTES` (30) and replays in full; its writes
   (Todoist, Calendar, Rouvy) happen twice.

## Goals / non-goals / anti-goals

- Goal: an approved continuation always runs once, even across a deploy.
- Goal: a scheduled run near the pass limit stops cleanly (the turn budget's
  wrap-up, "stopped: time") instead of being killed and replayed.
- Non-goal: "Run now" from the UI (the user watches it; unchanged).
- Non-goal: idempotent replays, a separate run worker (approaches B and C).
- Anti-goal: a new process on the production host (memory is tight); a resumed
  run that runs twice.

## Approaches

- **A (picked): hand both to the existing scheduler.** Approval records the
  continuation in the database; the next pass (at most ~1 min) runs it with the
  usual claiming and failure counting. Each pass has a deadline under systemd's
  limit and caps each run's time budget at what is left.
- B: a dedicated long-running run worker with a queue, leases and graceful
  deploys - robust for many busy agents, but a new process and deploy change.
- C: record each write per run and skip it on replay - treats consequences, per-tool work.

## Design

**Durable resume.**
- `scheduled_items` gets `resume_message TEXT` (migration). `_settle` stores the
  outcome text there (approved/rejected lines + "Re-issue exactly: ...") instead
  of starting a thread. The card says "Approved - continuing shortly."
- `claim_due_items` also claims active items with a `resume_message`, due or not.
- The pass runs such an item as today's approval resume does (`trigger="approval"`,
  that message, delivered with a push, tagged "after your answer"), then clears
  `resume_message` and gives the item back with its schedule unchanged (a resume
  is off-schedule, like `run_job_now`). A due regular run of the same item waits
  for the next pass.
- A resume that raises counts a failure like any run and keeps its message for
  the next pass; one killed by a crash is freed by the stale reset and runs again
  (the rare kill path, as today).
- `hold_reason` still applies (a new pending card or an exhausted budget holds it).

**Pass deadline.**
- The pass must end by `SCHEDULE_TICK_DEADLINE_SECONDS` (270, under systemd's 300).
- Before each model run: its time budget = min(`TURN_TIME_BUDGET_SECONDS`,
  time left to the deadline - `SCHEDULE_RUN_FINISH_MARGIN_SECONDS` (90: one tool
  round past the budget check plus the tools-off final call)). Below
  `SCHEDULE_MIN_RUN_SECONDS` (60) the run is not started: the item is given back
  unchanged and runs next pass (as `SCHEDULE_TICK_BUDGET_SECONDS` does today, which
  this replaces).
- The run's budget reaches the turn budget through the run's context (the graph
  state's `turn_started_at` clock with a per-run limit instead of the global one);
  `budget_stop`, `wrap_up_due` and `stop_facts` read that limit.

**Instrumented.** Log "Run resumed after cards" (item, waited seconds) and "Run
budget capped by the scheduler pass" (budget seconds); a run not started for lack
of time keeps today's line. Regular review: resumes per week and their wait; capped
runs and how many stopped on time. Re-measure ~Dec 15 2026 in TODO.

## Left to the builder

Where exactly the per-run limit lives (graph state key vs job context), test seams
for the pass clock, and the migration number at commit time.
