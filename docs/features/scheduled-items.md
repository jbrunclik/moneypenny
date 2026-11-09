# Jobs Set From Chat

Reminders, check-ins, watchers and recurring checks: the light jobs a user sets from a
message. Standing jobs (a standing chat's schedule, with grants) share their table,
scheduler and run path - see [Standing Chats and Jobs](agents.md).

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

- **Approved on a card, applied by the server:** `create` files a `schedule_item`
  [proposal](proposals.md) (when, how it ends) and stores nothing. The server stores
  exactly that item when the user taps **Set it up** or replies yes - so a page's injected
  "confirm", or fields that drifted since, cannot schedule something the user never saw.
  `text` and a watcher's `end_condition` go through the injection scan.
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
- **Runs** (`src/agent/item_runner.py`): ChatAgent in autonomous mode with a `JobContext`
  for the item (no grants) and only `web_search`, `fetch_url`, `research`; the user's
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
  the Command Center lists them with the standing jobs.
  API: `GET /api/conversations/<id>/schedules`, `DELETE /api/schedules/<id>`,
  `POST /api/schedules/<id>/pause|resume`.
- **Limits:** at most `SCHEDULE_MAX_ACTIVE_PER_USER` (20) items per user, paused included
  (the cap gates creating; restoring trashed or archived chats can bring a user above it -
  their items come back as they were rather than being dropped);
  a reminder's preview warns when none of the user's devices has notifications on.
- **Silent runs** (full agents too): the autonomous-agent prompt says to reply exactly
  `[SILENT]` when a check finds nothing new; the run saves it as "Nothing new." and
  skips the push (`is_silent_reply`, `should_push_run`).
- Evals: `schedule_reminder_preview`, `schedule_reminder_confirm`, `schedule_check_in_preview`,
  `schedule_watcher_preview`, `schedule_weekly_task`.

**Sidebar clock.** A chat with items shows a quiet clock in its sidebar row, with the
count from two on (`scheduled_count` on the conversation list and sync,
`light_item_counts()`); agents' own jobs are not counted. A watcher or recurring check
can become a full agent from Command Center ([agents.md](agents.md#command-center-ui)).

## See Also

- [Standing Chats and Jobs](agents.md) - standing jobs, the Command Center, approvals
- [Scheduled Jobs](../architecture/scheduled-jobs.md) - how the scheduler runs in production
- [Push Notifications](push-notifications.md) - delivery pushes
