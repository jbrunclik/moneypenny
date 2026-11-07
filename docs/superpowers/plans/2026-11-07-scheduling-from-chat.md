# Scheduling From Chat + Silent Runs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `schedule` tool creates one-off reminders (push, no model call) and recurring prompt-only agents from chat after an in-chat confirmation; scheduled agents can reply `[SILENT]` to skip the push.

**Architecture:** Reminders live in a new `reminders` table and are sent by the existing every-minute scheduler (`run_scheduled_agents`). Recurring tasks are ordinary agents created with `db.create_agent`. A pure helper turns the model's structured fields (date/time, days/time) into a UTC instant or a cron string in the household timezone. Silent runs: an instruction in the scheduled-agent prompt plus a check in the executor before the push.

**Tech Stack:** Python 3.14, SQLite + yoyo migrations, croniter, LangChain `@tool`, web push (`send_push_to_user`), pytest, the eval harness.

**Spec:** `docs/superpowers/specs/2026-11-07-scheduling-from-chat-design.md`

## Global Constraints

- Ordinary turns unchanged: the tool is only bound in ordinary, non-anonymous chats (not agents, programs, planner).
- Nothing is stored without `confirm=true`; the first `create` call returns a preview.
- Times are interpreted in `Config.APP_TIMEZONE`; stored instants are aware UTC (`src/utils/clock.py`, `src/db/models/timestamps.py` `to_db`/`from_db`).
- New env var `SCHEDULE_MAX_ACTIVE_PER_USER` (default 20): `src/config.py`, `.env.example`, the docs page.
- Migration number: the next free one (0075 today) - re-check main right before committing.
- Agent prompts and reminder texts go through `find_injection` (`src/utils/threat_patterns.py`).
- `/new-tool` checklist: `TOOL_METADATA` + `extract_tool_detail` branch, `_CONDITIONAL_TOOLS`, `lost_actions.SIDE_EFFECT_TOOLS`, `make prompt-snapshots`.

## Review Focus

1. "Remind me at 8" when 8:00 today has passed - refused with the current local time, not silently scheduled for a past instant.
2. A reminder due while the scheduler is down for 10 minutes - sent once when it comes back (late), never twice (two overlapping scheduler runs).
3. DST: "every day at 9" keeps 9:00 local across the change (cron in the household timezone, as agents already do).
4. "Cancel the plumber reminder" when two reminders match - the tool lists both with ids rather than deleting a guess.
5. A scheduled agent that writes `[SILENT]` with whitespace or a trailing period - still silent; one that writes real content mentioning "[SILENT]" mid-text - still pushes.

---

### Task 1: Reminders table and DB methods

**Files:**
- Create: `migrations/0075_add_reminders.py` (+ rollback)
- Create: `src/db/models/reminders.py` (mixin, registered on `Database` like the other mixins)
- Modify: `src/db/models/dataclasses.py` (`Reminder` dataclass)
- Test: `tests/integration/test_db_reminders.py`

**Interfaces:**
- Produces: `@dataclass Reminder: id: str; user_id: str; conversation_id: str | None; text: str; due_at: datetime; status: str  # "pending" | "sent" | "cancelled"; created_at: datetime`
- Produces: `add_reminder(user_id, conversation_id, text, due_at) -> Reminder`; `list_reminders(user_id, status="pending") -> list[Reminder]` (ordered by due_at); `cancel_reminder(reminder_id, user_id) -> bool`; `claim_due_reminders(now: datetime) -> list[Reminder]` - atomically flips due pending rows to "sent" (one `UPDATE ... RETURNING` or BEGIN IMMEDIATE) and returns them, so two scheduler runs never send one twice.

- [ ] **Step 1: Failing tests:** add/list ordering; cancel only own and only pending; `test_claim_due_reminders_returns_each_once` (claim twice -> second empty); future ones not claimed; cancelled not claimed.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/integration/test_db_reminders.py -n0` - FAIL.
- [ ] **Step 3: Implement** migration (table `reminders`, index on `(status, due_at)`), dataclass, mixin.
- [ ] **Step 4: Run** the tests plus `tests/unit/test_migration_chain.py` - PASS.
- [ ] **Step 5: Commit** `feat(reminders): reminders table and DB methods`.

### Task 2: Schedule spec builder

**Files:**
- Create: `src/utils/schedule_spec.py`
- Test: `tests/unit/test_schedule_spec.py`

**Interfaces:**
- Produces: `one_off_instant(date: str, time: str, tz: str, now: datetime) -> datetime | ScheduleError` - aware UTC; errors for a bad format or a time in the past (naming the current local time).
- Produces: `recurring_cron(days: list[str], time: str) -> ScheduleError | str` - a cron string like `"0 9 * * 1"`; `days` items `mon..sun`, or `["daily"]`, `["weekdays"]`, `["weekends"]`.
- Produces: `@dataclass(frozen=True) class ScheduleError: message: str` - returned (not raised) for any invalid input; `one_off_instant` returns `datetime | ScheduleError` too.
- Produces: `describe(...) -> str` human text for previews ("Fri 13 Nov 08:00", "Every Monday at 09:00").

- [ ] **Step 1: Failing tests:** `"2026-11-13","08:00","Europe/Prague"` -> 07:00 UTC; past -> error mentioning local now; `["mon"],"09:00"` -> `"0 9 * * 1"`; `["weekdays"],"07:30"` -> `"30 7 * * 1-5"`; `["daily"],"08:00"` -> `"0 8 * * *"`; bad `"25:00"` / `"funday"` -> errors; DST: `one_off_instant("2026-03-29","09:00",...)` -> 07:00 UTC (CEST).
- [ ] **Step 2-4:** run (FAIL), implement with `zoneinfo`, run (PASS).
- [ ] **Step 5: Commit** `feat(schedule): build reminder instants and cron strings in code`.

### Task 3: The scheduler sends due reminders

**Files:**
- Modify: `src/agent/scheduler.py` (`run_scheduled_agents` also calls `send_due_reminders(now)`; `SchedulerResult` gains `reminders_sent: int`)
- Test: `tests/unit/test_scheduler_reminders.py`

**Interfaces:**
- Consumes: `claim_due_reminders` (Task 1).
- Produces: `send_due_reminders(now: datetime) -> int` - for each claimed reminder `send_push_to_user(user_id, "Reminder", text[:160], url=f"/#/conversations/{conversation_id}" if conversation_id else "/", tag=f"reminder-{id}")`; a push failure is logged, not retried (the row is already sent).

- [ ] **Step 1: Failing tests:** a due reminder pushes once with the text and conversation url; a second scheduler run sends nothing; a future one sends nothing.
- [ ] **Step 2-4:** run, implement, run.
- [ ] **Step 5: Commit** `feat(reminders): the scheduler pushes due reminders`.

### Task 4: The `schedule` tool

**Files:**
- Create: `src/agent/tools/schedule.py`
- Modify: `src/agent/tools/__init__.py` (bind in `_ordinary_chat_tools` when not anonymous; export), `src/agent/tool_display.py` (metadata + detail), `src/api/helpers/lost_actions.py` (`SIDE_EFFECT_TOOLS`), `src/config.py` + `.env.example` (`SCHEDULE_MAX_ACTIVE_PER_USER=20`), prompt snapshots
- Test: `tests/unit/test_schedule_tool.py`

**Interfaces:**
- Consumes: Tasks 1-2; `db.create_agent`, `db.update_agent`/enable toggle, `db.delete_agent` (look up the exact names in `src/db/models/agent.py`); `find_injection`.
- Produces: `schedule(action: str, kind: str | None = None, text: str | None = None, date: str | None = None, time: str | None = None, days: list[str] | None = None, item_id: str | None = None, confirm: bool = False) -> str`
  - `action="create"`, `kind="reminder"`: `text`, `date`, `time`. `kind="task"`: `text` (the task prompt), `days`, `time`, optional name derived from text.
  - Without `confirm`: returns `PREVIEW: <describe> - "<text>". Nothing is scheduled yet: ask the user to confirm, then call again with confirm=true.`
  - With `confirm=true`: stores; returns `Scheduled reminder id=... for Fri 13 Nov 08:00 (Europe/Prague)` / `Created recurring task id=<agent id> ... - it appears in the Command Center`.
  - `action="list"`: pending reminders + chat-created agents (agents whose `description` starts with `"Created from chat"`), each with id, when, text.
  - `action="pause"|"resume"|"delete"` with `item_id` (reminder or agent id); reminders support delete only (pause -> "delete and re-create"). Unknown/foreign id -> error naming `list`.
  - Refusals: injection in `text`; over the active cap (count pending reminders + enabled chat agents); bad schedule from Task 2; called inside a scheduled run (`get_agent_context()` not None) - defence in depth, the tool is not bound there.

- [ ] **Step 1: Failing tests** (test database + `set_conversation_context`): preview stores nothing; confirmed reminder stored with the right UTC instant; confirmed task creates an agent with cron `0 9 * * 1`, timezone `Config.APP_TIMEZONE`, description `Created from chat ...`; list shows both; delete reminder; pause/resume task; foreign id refused; injection refused; cap refused; agent context refused; not bound in anonymous mode or for agents (`get_tools_for_request`).
- [ ] **Step 2-4:** run, implement, run + `make prompt-snapshots` + `tests/unit/test_tool_display.py tests/unit/test_prompt_snapshots.py`.
- [ ] **Step 5: Commit** `feat(schedule): reminders and recurring tasks from chat, confirmed in chat`.

### Task 5: Silent runs

**Files:**
- Modify: the scheduled-agent prompt (`src/agent/prompt_agents.py` - find where the agent run's system prompt is assembled), `src/agent/executor.py` (before `_notify_run_finished`)
- Test: `tests/unit/test_executor.py` (or a new `tests/unit/test_silent_runs.py`)

**Interfaces:**
- Produces: `is_silent_reply(text: str) -> bool` - true when the stripped reply, minus trailing punctuation, is exactly `[SILENT]` (case-insensitive); the executor then saves "Nothing new." as the reply content and skips the push.

- [ ] **Step 1: Failing tests:** `is_silent_reply` true for `"[SILENT]"`, `" [silent]. "`, false for `"Found 2 new items. [SILENT]"`; a scheduled run replying `[SILENT]` sends no push and stores "Nothing new."; a normal reply pushes as before; the scheduled-agent prompt contains the `[SILENT]` instruction.
- [ ] **Step 2-4:** run, implement, run.
- [ ] **Step 5: Commit** `feat(agents): a scheduled run with nothing new stays silent`.

### Task 6: Evals, docs, TODO

**Files:**
- Create: `evals/cases/schedule_reminder_confirm.yaml` (history: user asks "remind me tomorrow at 8 to call the plumber", assistant previews; current user: "yes" -> `required_tools: [schedule]`, rubric: confirms the reminder for tomorrow 08:00) and `evals/cases/schedule_reminder_preview.yaml` (single turn: must NOT confirm without asking - rubric: asks to confirm, `forbidden_arg_patterns: {schedule.confirm: ['True']}`), `evals/cases/schedule_weekly_task.yaml` (Czech: "každé pondělí v 9 mi zkontroluj školní jídelníček" -> preview with Monday 09:00)
- Modify: `docs/features/agents.md` (or a new section in the push/agents page: reminders, the tool, silent runs), `TODO.md` (remove "Scheduling from chat" and the "Silent runs" sub-item)

- [ ] **Step 1:** write the cases; run each 3x - report cost; check stored rows in the eval DB where possible.
- [ ] **Step 2:** docs + TODO.
- [ ] **Step 3:** `make pre-commit` green (new tool + migration + scheduler: full suite).
- [ ] **Step 4: Commit** `test(evals)/docs: scheduling from chat`; push; deploy; verify on the production host the scheduler timer still runs (`journalctl` shows the scheduler's run line with `reminders_sent`).
