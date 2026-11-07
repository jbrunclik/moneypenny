# Lightweight Agents From Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reminders, check-ins, watchers and recurring items set from chat become lightweight items that live with their chat (header chip, results delivered as turns there), show in a "From chats" lane in the Command Center, and clean up after themselves.

**Architecture:** The `reminders` table becomes `scheduled_items` (one row per item, `conversation_id` required). Items follow their chat by query - only items whose chat is live (not trashed, not archived) run or show - and a SQLite trigger deletes them when the chat row is deleted. The every-minute scheduler claims due items atomically; one-offs fire without a model call; watchers and recurring items run through the agent machinery with an in-memory `Agent` (no row) and the always-safe tools, and deliver labelled assistant turns into the originating chat.

**Tech Stack:** Flask + Pydantic schemas (OpenAPI → TS types), SQLite + yoyo, LangGraph `ChatAgent`, croniter, vanilla TS + Zustand, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-07-lightweight-agents-design.md` (builds on `docs/superpowers/specs/2026-11-07-scheduling-from-chat-design.md`).

## Global Constraints

- Production daily driver, 4 users; the repo is public - no hostnames/infra in docs or commits.
- Multi-worker production (2 gunicorn workers + the scheduler process): no per-process state; claims are a single `UPDATE ... RETURNING`.
- New env vars: `src/config.py` default + `.env.example` + `docs/features/agents.md`.
- New migration: check the highest number on main right before committing (plan assumes `0076`, depends on `0075_add_reminders`); any pending `reminders` rows must survive.
- Tool changes: `make prompt-snapshots`; evals for check-in and watcher creation, report cost.
- UI: desktop and mobile (768px breakpoint), both themes, liquid-glass surfaces, uniform vertical rhythm; no suggestion chips; icons from `web/src/utils/icons.ts`.
- `SCHEDULE_MAX_ACTIVE_PER_USER` (20) counts all four kinds, paused included.
- Watcher interval: `6h`, `daily` (default) or `weekly` - never more often than 6 hours; back-off doubles the interval after 7 consecutive quiet runs, up to weekly, not for watchers with an until-date; expiry default 30 days; stop after 3 consecutive failures.
- Silent runs (`[SILENT]`) post nothing and push nothing; `[DONE]` ends a watcher.
- Finished items (fired, done, expired, cancelled) are deleted; the chat holds the record.
- Gate before each commit: `make lint` + the full suite (`E2E_PORT=8041 caffeinate -i nice -n 10 make pre-commit`, check the exit code). Stage explicit paths only.

## Review Focus

1. A reminder due while the scheduler was down 3 hours still fires (late, once); one 7 hours late is "missed" (note in the chat, no push) - the same rule as a chat restored from the trash after its time passed. Test: Task 4 `test_late_within_grace_fires` / `test_late_past_grace_is_missed`.
2. Two overlapping scheduler runs never run a watcher twice, and a run that crashed mid-way (status stuck `running`) is picked up again after 30 minutes. Test: Task 1 `test_claim_marks_running_once` / `test_stale_running_is_reset`.
3. A watcher reply of `[DONE]` with whitespace, a trailing dot, backticks or lowercase - alone or before/after the report - ends the watcher and the marker never shows in the delivered text; "[DONE]" quoted mid-sentence does not. Test: Task 3 `test_done_marker_variants`.
4. Trash a chat → its items vanish from the chip, the lane and the scheduler; restore → back; delete permanently or purge → gone for good. Test: Task 1 `test_items_follow_their_chat` / `test_delete_conversation_deletes_items`, Task 5 route test.
5. Resuming a watcher paused for two weeks runs it once on the next tick, not once per missed interval; resuming never exceeds the cap because paused items count. Test: Task 4 `test_resume_runs_once`, Task 2 `test_paused_items_count_toward_the_cap`.

---

### Task 1: The `scheduled_items` table, its DB methods, and message delivery labels

**Files:**
- Create: `migrations/0076_scheduled_items.py`
- Create: `src/db/models/scheduled_items.py` (replaces `src/db/models/reminders.py` - delete it)
- Modify: `src/db/models/dataclasses.py` (replace `Reminder` with `ScheduledItem`; add `MessageDelivery`; `Message.delivery`)
- Modify: `src/db/models/__init__.py` (mixin swap), `src/db/models/message.py` + `src/db/models/message_rows.py` (`delivery` column)
- Test: `tests/integration/test_db_scheduled_items.py` (replaces `tests/integration/test_db_reminders.py` - delete it)

**Interfaces:**
- Produces:
  - `ItemKind = Literal["reminder", "check_in", "watcher", "recurring"]`
  - `@dataclass ScheduledItem: id, user_id, conversation_id: str, kind: ItemKind, text: str, end_condition: str | None, schedule: str | None (cron, recurring), interval_hours: int | None (watcher), next_run_at: datetime, expires_at: datetime | None, status: Literal["active", "paused", "running"], last_result: str | None, quiet_runs: int, failures: int, created_at: datetime, claimed_at: datetime | None`
  - `class MessageDelivery(TypedDict): kind: ItemKind; label: str`
  - `db.add_item(item: ScheduledItem) -> ScheduledItem`
  - `db.get_item(item_id: str, user_id: str) -> ScheduledItem | None`
  - `db.list_items(user_id: str, conversation_id: str | None = None) -> list[ScheduledItem]` - live chats only, soonest `next_run_at` first
  - `db.count_items(user_id: str) -> int` - all statuses, live chats only
  - `db.set_item_paused(item_id: str, user_id: str, paused: bool) -> bool`
  - `db.delete_item(item_id: str, user_id: str | None = None) -> bool` (None = scheduler-internal)
  - `db.claim_due_items(now: datetime) -> list[ScheduledItem]` - `active` + `next_run_at <= now` + live chat → `running`, `claimed_at=now`, returned
  - `db.finish_item_run(item_id: str, next_run_at: datetime, last_result: str | None, quiet_runs: int, failures: int) -> None` - back to `active`
  - `db.reset_stale_runs(now: datetime, stale_minutes: int) -> int`
  - `db.add_message(..., delivery: MessageDelivery | None = None)`; `Message.delivery: MessageDelivery | None`

- [ ] **Step 1: Write the failing tests** in `tests/integration/test_db_scheduled_items.py` (fixtures `test_database`, `test_user`, `test_conversation`; a small `_item(**overrides)` builder):
  - `test_add_and_list_soonest_first`
  - `test_items_follow_their_chat` - trash the chat → `list_items` and `claim_due_items` return nothing; `restore_conversation` → both return it; same for `archive_conversation` / `unarchive_conversation`
  - `test_delete_conversation_deletes_items` - `delete_conversation` → no row left (`SELECT COUNT(*) FROM scheduled_items` = 0); same via `empty_trash`
  - `test_claim_marks_running_once` - two `claim_due_items(now)` calls → the item comes back once; status `running`
  - `test_paused_is_not_claimed`
  - `test_stale_running_is_reset` - claimed 31 min ago → `reset_stale_runs(now, 30) == 1` and it is claimable again; claimed 5 min ago → 0
  - `test_finish_item_run_sets_next_and_state`
  - `test_scoped_to_user` - another user's `get_item` / `delete_item` / `set_item_paused` → None / False
  - `test_message_delivery_round_trips` - `add_message(..., delivery={"kind": "check_in", "label": "Check-in · Fri 18:00"})` → `get_messages` returns it; absent → None

- [ ] **Step 2: Run them** - `.venv/bin/python -m pytest -q -n0 tests/integration/test_db_scheduled_items.py` → FAIL (no table / methods).

- [ ] **Step 3: Write `migrations/0076_scheduled_items.py`** (`__depends__ = {"0075_add_reminders"}`), self-contained SQL steps:
  - `CREATE TABLE scheduled_items` with the dataclass columns (`conversation_id TEXT NOT NULL`, `kind` and `status` with CHECK constraints, `quiet_runs`/`failures` INTEGER DEFAULT 0), indexes `(status, next_run_at)`, `(user_id)`, `(conversation_id)`.
  - Copy `reminders` rows with `status='pending' AND conversation_id IS NOT NULL` as `kind='reminder'`, `next_run_at=due_at`, `status='active'`; then `DROP TABLE reminders`.
  - `CREATE TRIGGER scheduled_items_follow_conversation AFTER DELETE ON conversations BEGIN DELETE FROM scheduled_items WHERE conversation_id = OLD.id; END`.
  - Delete chat-created agents (`autonomous_agents.description LIKE 'Created from chat%'`) with their `agent_executions`, their run conversations' messages and the conversations (production had 0 on Nov 7 2026 - re-check before landing).
  - `ALTER TABLE messages ADD COLUMN delivery TEXT`.
  - Rollback steps for each (rollback recreates `reminders` empty).

- [ ] **Step 4: Implement the mixin and dataclass changes.** "Live chat" is one SQL fragment used by `list_items`, `count_items` and `claim_due_items`: `conversation_id IN (SELECT id FROM conversations WHERE deleted_at IS NULL AND (archived = 0 OR archived IS NULL))`. `delivery` is stored as JSON like `action`.

- [ ] **Step 5: Run the tests** → PASS. Then remove every reference to `Reminder`/`RemindersMixin`/`add_reminder`/`list_reminders`/`cancel_reminder`/`claim_due_reminders` that this breaks only as far as Tasks 2 and 4 need - leave the tool and scheduler to those tasks, but the suite must import cleanly: `grep -rn "reminder" src/ --include=*.py`.

- [ ] **Step 6: Commit** `feat(schedule): scheduled items table that follows its chat` (migration, mixin, dataclasses, message delivery, tests).

### Task 2: The `schedule` tool - check-ins, watchers, recurring items as items

**Files:**
- Modify: `src/agent/tools/scheduling.py`, `src/utils/schedule_spec.py`, `src/config.py`, `.env.example`
- Test: `tests/unit/test_schedule_tool.py`, `tests/unit/test_schedule_spec.py`

**Interfaces:**
- Consumes: Task 1's `ScheduledItem`, `db.add_item`, `db.list_items`, `db.count_items`, `db.set_item_paused`, `db.delete_item`, `db.get_item`.
- Produces:
  - `schedule_spec.watch_interval_hours(hint: str) -> int | ScheduleError` - `"6h"`→6, `"daily"`→24, `"weekly"`→168; anything else → error naming the three
  - `schedule_spec.until_instant(day: str, tz: str, now: datetime) -> datetime | ScheduleError` - end of that local day; past → error
  - `schedule_spec.describe_interval(hours: int) -> str` - "every 6 hours" / "daily" / "weekly" / "every N days"
  - Tool signature: `schedule(action, kind=None, text=None, date=None, time=None, days=None, until=None, interval=None, end_condition=None, item_id=None, confirm=False)`
  - Config: `SCHEDULE_WATCH_EXPIRY_DAYS: int = 30`
  - Constants (`src/agent/tools/scheduling.py` or `src/constants.py`): `WATCH_MIN_INTERVAL_HOURS = 6`, `WATCH_MAX_INTERVAL_HOURS = 168`

- [ ] **Step 1: Write the failing tests.** Keep the confirm-gate, injection, agent-context and no-push-device tests (adapt to items). New, in `tests/unit/test_schedule_tool.py`:
  - `test_a_check_in_previews_its_question_and_stores_it` - `kind="check_in", text="How's the tail looking - is the fur growing back?", date, time` → preview contains the question and "then done"; after confirm `list_items` has one `check_in` with that text and `next_run_at` = the local time in UTC
  - `test_a_watcher_previews_how_it_ends` - `kind="watcher", text="the school's job board", end_condition="a teacher job is posted", interval="daily"` → preview contains "daily", "until a teacher job is posted" and "at most 30 days"; confirmed item has `interval_hours=24`, `expires_at = now + 30 days`, `next_run_at` = now (first check on the next tick)
  - `test_a_watcher_until_date_sets_expiry` - `until="2026-12-24"` → `expires_at` = end of 24 Dec Prague time; preview says "until 24 Dec"
  - `test_a_watcher_more_often_than_6h_is_refused` - `interval="1h"` → error naming 6h/daily/weekly
  - `test_a_recurring_item_is_not_an_agent` - `kind="recurring"` confirmed → one item `kind="recurring"`, `schedule="0 9 * * 1"`, `expires_at is None`; `db.list_agents_with_status(user.id) == []`
  - `test_a_recurring_until_date_sets_expiry` - `until` works for recurring too (the spec's optional end date); preview says "until <date>"
  - `test_paused_items_count_toward_the_cap` - cap 1, one paused item → next confirm refused
  - `test_list_shows_all_kinds_with_how_they_end`
  - `test_delete_pause_resume_by_id` - pause/resume only for watcher/recurring ("A reminder cannot be paused" kept for one-offs)
  - in `tests/unit/test_schedule_spec.py`: `test_watch_interval_hours`, `test_until_instant`, `test_describe_interval`

- [ ] **Step 2: Run them** - `.venv/bin/python -m pytest -q -n0 tests/unit/test_schedule_tool.py tests/unit/test_schedule_spec.py` → FAIL.

- [ ] **Step 3: Implement.** The pending preview (kv `schedule_pending`) now holds every field `ScheduledItem` needs; `_confirm` builds the item from it. Items always carry the current `conversation_id` (refuse without one). Delete `CHAT_TASK_PREFIX`, `_chat_tasks`, `_task_name` and the `create_agent` path. Tool docstring: the four kinds, that a check-in's `text` is the question to ask then (written now, from the conversation), that a watcher's `text` says what to check and `end_condition` when to stop, and that watchers see only public web pages. Previews end with how the item ends ("then done" / "until <condition>, at most <N> days" / "until cancelled").

- [ ] **Step 4: Run the tests** → PASS; then `make prompt-snapshots` and check the diff is only the `schedule` declaration.

- [ ] **Step 5: Commit** `feat(schedule): check-ins, watchers and recurring items from chat` (tool, spec helpers, config, `.env.example`, snapshots, tests).

### Task 3: Running a model-backed item and delivering into its chat

**Files:**
- Create: `src/agent/item_runner.py`, `src/agent/prompt_texts/scheduled_items.py`
- Test: `tests/unit/test_item_runner.py`

**Interfaces:**
- Consumes: Task 1's `ScheduledItem`, `MessageDelivery`, `db.add_message(delivery=...)`; existing `get_tools_for_agent`, `ChatAgent.chat_batch`, `set_agent_context`/`clear_agent_context`, `set_conversation_context`, `calculate_and_save_message_cost`, `send_push_to_user`, `is_silent_reply` (`src/agent/executor.py`).
- Produces:
  - `@dataclass RunOutcome: status: Literal["silent", "report", "done", "failed"]; text: str; error: str | None = None`
  - `DONE_MARKER = "[DONE]"`
  - `parse_reply(raw: str) -> RunOutcome` - silent / done (marker at the very start or end, tolerant of whitespace, a trailing dot, backticks, `*`, any case; marker stripped from `text`) / report
  - `run_model_item(item: ScheduledItem, user: User) -> RunOutcome` - never raises; tool/model errors → `failed`
  - `deliver(item: ScheduledItem, text: str, label: str, push: bool = True) -> Message` - assistant message in `item.conversation_id` with `delivery={"kind": item.kind, "label": label}`, push titled by kind opening `/#/conversations/<id>`
  - `delivery_label(kind: ItemKind, when: datetime, tz: str, outcome: str | None = None) -> str` - "Check-in · Fri 18:00", "Watcher · found", "Watcher · update", "Recurring · Mon 09:00", "Watcher · stopped"

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_item_runner.py` (patch `ChatAgent` like `tests/unit/test_executor.py` does):
  - `test_done_marker_variants` - parametrize `"[DONE] Posted: teacher job"`, `"Posted.\n[done]"`, `"`[DONE]` Posted"`, `"**[DONE]** Posted"` → `done`, text has no marker; `"The page says [DONE] is a tag"` → `report`
  - `test_silent_reply_is_silent` - `"[SILENT]"`, `" `[SILENT]`. "` → `silent`
  - `test_run_uses_only_safe_tools_and_no_agent_row` - the tools passed to `ChatAgent` ⊆ `ALWAYS_SAFE_TOOLS`; `db.list_agents_with_status(user.id) == []` after the run
  - `test_the_prompt_carries_condition_and_previous_result` - the trigger text sent to `chat_batch` contains `item.text`, `item.end_condition` and `item.last_result`
  - `test_schedule_tool_is_refused_inside_a_run` - `get_agent_context()` is set during `chat_batch`
  - `test_model_error_is_failed_not_raised`
  - `test_silent_run_records_its_cost_against_the_chat` - a `message_costs` row with `conversation_id=item.conversation_id` and `message_id` starting `silent:`
  - `test_deliver_posts_a_labelled_turn_and_pushes`

- [ ] **Step 2: Run them** - `.venv/bin/python -m pytest -q -n0 tests/unit/test_item_runner.py` → FAIL.

- [ ] **Step 3: Implement.** `run_model_item` builds an in-memory `Agent` (`id=f"item-{item.id}"`, `conversation_id=item.conversation_id`, `tool_permissions=[]`, `fresh_context=True`, `name` = item text truncated to 40 chars, `model=Config.DEFAULT_MODEL`, `system_prompt` from `prompt_texts/scheduled_items.py`) and reuses `_prompt_context`-style context with the autonomous agent prompt; it sets and always clears the run contextvars (try/finally). The watcher prompt tells the model: what to check, the end condition, the previous result ("report only what changed since"), reply `[SILENT]` when nothing changed, start with `[DONE]` when the condition is met. Recurring uses the same prompt minus the `[DONE]` instruction. A delivered run's cost attaches to the delivered message; a silent run's to `message_id=f"silent:{uuid4()}"` (`mode="item"`).

- [ ] **Step 4: Run the tests** → PASS.

- [ ] **Step 5: Commit** `feat(schedule): run watchers and recurring items into their chat`.

### Task 4: The scheduler drives items through their lifecycle

**Files:**
- Create: `src/agent/item_scheduler.py`
- Modify: `src/agent/scheduler.py` (`send_due_reminders` → `run_due_items`; `SchedulerResult.reminders_sent` → `items_fired`, `items_run`), `src/config.py`, `.env.example`
- Test: `tests/unit/test_item_scheduler.py` (replaces `tests/unit/test_scheduler_reminders.py` - delete it), `tests/unit/test_scheduler.py`

**Interfaces:**
- Consumes: Task 1's DB methods, Task 3's `run_model_item`, `deliver`, `delivery_label`, `parse_reply`; Task 2's `describe_interval`.
- Produces:
  - `@dataclass ItemsResult: fired: int = 0; run: int = 0; missed: int = 0; expired: int = 0`
  - `run_due_items(now: datetime) -> ItemsResult`
  - `next_watch_run(now: datetime, interval_hours: int, quiet_runs: int, has_until: bool) -> datetime` - doubles `interval_hours` per full 7 quiet runs (`quiet_runs // 7`), capped at 168, no back-off when `has_until`
  - Config: `SCHEDULE_MISSED_GRACE_HOURS: int = 6`, `SCHEDULE_WATCH_BACKOFF_AFTER: int = 7`, `SCHEDULE_ITEM_MAX_FAILURES: int = 3`, `SCHEDULE_RUN_STALE_MINUTES: int = 30`

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_item_scheduler.py`:
  - `test_reminder_pushes_and_is_deleted` - push called once, no message in the chat, item gone
  - `test_check_in_posts_a_labelled_turn_pushes_and_is_deleted` - one assistant message with `delivery.kind == "check_in"`, text = the question
  - `test_late_within_grace_fires` - due 3 h ago → fires
  - `test_late_past_grace_is_missed` - due 7 h ago → an assistant turn "Missed (was due Fri 13 Nov 08:00): <text>", no push, item gone. The scheduler cannot tell a trashed-then-restored chat from downtime, so the copy names the due time, not the trash (deviation from the spec's "Missed while this chat was in the trash" wording - ledger it)
  - `test_recurring_until_date_expires_quietly` - `expires_at <= now` → deleted with a "Stopped: reached its end date" turn, no push
  - `test_watcher_silent_backs_off` - 7 quiet runs on `daily` → next run in 48 h; `has_until` → 24 h
  - `test_watcher_report_delivers_and_resets_quiet_runs`
  - `test_watcher_done_delivers_and_is_deleted`
  - `test_watcher_expired_posts_stopped_turn_without_push` - `expires_at <= now` → "Stopped watching: …" turn, no push, item gone
  - `test_three_failures_stop_the_watcher` - third consecutive `failed` → "Stopped watching - kept failing" turn, item gone; a success in between resets the count
  - `test_recurring_runs_on_its_cron_and_stays` - next run from croniter in the household timezone
  - `test_resume_runs_once` - a watcher with `next_run_at` two weeks ago runs once and gets one future `next_run_at`
  - `test_stale_runs_are_reset_each_tick`
  - In `tests/unit/test_scheduler.py`: the completed log line carries `items_fired` and `items_run`; items run before agents.

- [ ] **Step 2: Run them** → FAIL.

- [ ] **Step 3: Implement** `run_due_items`: `reset_stale_runs`, claim, then per item - one-offs: missed if `now - next_run_at > grace`, else reminder push / check-in `deliver`, then `delete_item`; expired watchers: stopped turn + delete; watcher/recurring: `run_model_item` → silent (quiet_runs+1, `finish_item_run`), report (deliver, quiet_runs=0), done (deliver "found", delete), failed (failures+1; at the max → stopped turn + delete; else `finish_item_run` on the normal interval). Each item in its own try/except so one bad item cannot stop the tick. Replace the scheduler's reminders call and log fields.

- [ ] **Step 4: Run the tests** → PASS; then `.venv/bin/python -m pytest -q tests/unit tests/integration` (whole backend).

- [ ] **Step 5: Commit** `feat(schedule): the scheduler fires, runs, backs off and cleans up items`.

### Task 5: API - per-chat items, the Command Center lane, delivery labels

**Files:**
- Create: `src/api/schemas/schedules.py`, `src/api/routes/schedules.py`
- Modify: `src/api/routes/__init__.py` (register + route count docstring), `src/api/schemas/agents.py` (`CommandCenterResponse.chat_items`), `src/api/routes/agent_command_center.py`, `src/api/schemas/chat.py` (`MessageResponse.delivery`), the message→response mapping, `static/openapi.json` + `web/src/types/generated-api.ts` (via `make openapi && make types`), `web/src/types/api.ts`, `web/src/api/agents.ts` (or a new `web/src/api/schedules.ts`)
- Test: `tests/integration/test_routes_schedules.py`, `tests/integration/test_routes_agent_command_center.py`

**Interfaces:**
- Consumes: Task 1's DB methods; Task 2's `describe_instant`, `describe_cron`, `describe_interval`.
- Produces:
  - `ScheduledItemResponse(ResponseModel)`: `id`, `conversation_id`, `conversation_title: str`, `kind`, `title: str` (text truncated to 60), `when: str` (human, household tz: "Fri 13 Nov 18:00", "every Monday at 09:00", "daily"), `ends: str` ("then done" / "until <condition> · at most until 7 Dec" / "until cancelled"), `status: Literal["active", "paused", "running"]`, `next_run_at: datetime`
  - `DeliveryResponse(ResponseModel)`: `kind`, `label`
  - `GET /api/conversations/<conv_id>/schedules` → `{conversation_id, items: list[ScheduledItemResponse]}` (404 for another user's chat)
  - `DELETE /api/schedules/<item_id>` → 204; `POST /api/schedules/<item_id>/pause` and `/resume` → the item (409 for one-offs)
  - `CommandCenterResponse.chat_items: list[ScheduledItemResponse]` (all live items, soonest first)
  - TS client: `schedules.forConversation(convId)`, `schedules.remove(id)`, `schedules.pause(id)`, `schedules.resume(id)`

- [ ] **Step 1: Write the failing integration tests** (`client`, `test_user`, `auth_headers`): list for a chat (only that chat's items); another user's chat → 404; delete → 204 and gone; pause/resume a watcher; pause a reminder → 409; a trashed chat's items absent from both endpoints and back after restore; `GET /api/agents/command-center` carries `chat_items`; a message with `delivery` returns it from the conversation messages endpoint.

- [ ] **Step 2: Run them** → FAIL.

- [ ] **Step 3: Implement** per `.claude/rules/api.md` (schemas in the feature module, `@require_auth`, `raise_*_error`, thin routes); `make openapi && make types`; client methods.

- [ ] **Step 4: Run** `.venv/bin/python -m pytest -q -n0 tests/integration/test_routes_schedules.py tests/integration/test_routes_agent_command_center.py` → PASS; `make lint` → exit 0.

- [ ] **Step 5: Commit** `feat(api): scheduled items per chat and in the Command Center`.

### Task 6: UI - the chat chip, the "From chats" lane, delivered-turn labels

**Files:**
- Create: `web/src/components/ScheduleIndicator.ts`, `web/src/styles/components/schedule-indicator.css`
- Modify: `web/src/core/startup/app-shell.ts` (desktop + mobile chip buttons beside the facts chip), the startup module that initialises `FactsIndicator` (init the new one next to it), `web/src/components/CommandCenter.ts` (+ its CSS), the assistant-message renderer under `web/src/components/messages/` (label above the content when `message.delivery`), `web/src/styles/components/chat-header.css` (mobile chip ordering)
- Test: `web/tests/unit/` (component test for the indicator and the label), `web/tests/e2e/scheduled-items.spec.ts`

**Interfaces:**
- Consumes: Task 5's `ScheduledItemResponse`, `DeliveryResponse`, `CommandCenterResponse.chat_items`, the TS client.
- Produces: `initScheduleIndicator(): void`, `refreshScheduleIndicator(): Promise<void>` (called on conversation switch and after each completed turn), `renderChatItemsSection(items, handlers): HTMLDivElement | null` in `CommandCenter.ts`.

- [ ] **Step 1: Write the failing tests:**
  - Unit: the chip is hidden with no items and shows the count otherwise; the popup lists title, when and ends, with cancel (and pause/resume only for watcher/recurring); a message with `delivery` renders its label above the text; without it, nothing extra.
  - E2E `scheduled-items.spec.ts` (desktop and mobile projects; seed items through the e2e server's DB helpers or the tool's routes): chip count, cancel from the popup removes the item and hides the chip; the Command Center shows "From chats" above the agents with a link that opens the chat; a delivered check-in turn shows its label; a trashed chat's items do not show in the lane.

- [ ] **Step 2: Run them** (`cd web && npx vitest run <unit file>`; `make build && E2E_PORT=8041 npx playwright test e2e/scheduled-items.spec.ts --project=chromium`) → FAIL.

- [ ] **Step 3: Implement.** Copy `FactsIndicator.ts`'s structure (UI-local state per open conversation, refetch on switch, `createPopup`). Icons: `BELL_ICON` reminder, `CLOCK_ICON` check-in, `SEARCH_ICON` watcher, `HISTORY_ICON` recurring; chip shows `CLOCK_ICON` + count. Lane: a section titled "From chats" above the agents section, hidden when empty, one row per item (icon, title, `when · ends`, chat title as a link, cancel). Label: small muted line ("Check-in · Fri 18:00") above the assistant content, liquid-glass tokens, both themes.

- [ ] **Step 4: Run** unit + E2E on chromium and webkit, desktop and mobile → PASS; screenshot desktop and mobile and check vertical rhythm.

- [ ] **Step 5: Commit** `feat(ui): scheduled items in their chat and the Command Center`. If a visual baseline changed, follow `/regen-baselines` in a separate commit.

### Task 7: Evals, docs, gate, deploy

**Files:**
- Create: `evals/cases/schedule_check_in_preview.yaml`, `evals/cases/schedule_watcher_preview.yaml`
- Modify: `evals/cases/schedule_weekly_task.yaml` (recurring item wording), `docs/features/agents.md` (replace "Scheduling From Chat" with the four kinds, lifecycle, UI, env vars), `docs/features/push-notifications.md` (delivered turns push), `TODO.md` (remove "Self-stopping watchers" and the "Replies continue the delivery" part covered for items; keep the rest of "Quieter, smarter watchers")

- [ ] **Step 1: Write the eval cases** - check-in: a chat about a pet's injured tail, user "check with me on Friday evening how it's healing" → `schedule` create `kind="check_in"` without confirm, preview asks a specific question about the tail; watcher: "let me know when the school posts a teacher job" (with the school's URL) → `kind="watcher"`, an end condition, no confirm. `forbidden_arg_patterns` on `schedule.confirm` `^True$`.

- [ ] **Step 2: Run** `PYTHONPATH=. nice -n 10 .venv/bin/python evals/run.py --only schedule_check_in_preview,schedule_watcher_preview,schedule_weekly_task,schedule_reminder_preview,schedule_reminder_confirm` three times → all pass (report the USD cost).

- [ ] **Step 3: Docs + TODO** as listed; `docs/features/agents.md` names every new env var.

- [ ] **Step 4: Gate** - `E2E_PORT=8041 caffeinate -i nice -n 10 make pre-commit` → exit 0.

- [ ] **Step 5: Commit** `test(evals)/docs: lightweight agents from chat`; re-check the production counts (chat-created agents, pending reminders) read-only, push, deploy, health-check, and confirm the scheduler log line shows `items_fired`/`items_run`.
