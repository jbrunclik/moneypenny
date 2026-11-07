# Lightweight Agents From Chat - Design

Discussed in chat with Jiri on Nov 7 2026. Builds on
[scheduling from chat](2026-11-07-scheduling-from-chat-design.md) (the `schedule` tool,
the `reminders` table, the confirm gate, silent runs), shipped the same day.

## Why

A sweep of the last 30 days (291 conversations, all four users, Flash-Lite, aggregates
only) found about one conversation in five wanting something to happen *later*:

| Kind | Conversations | Explicitly asked |
|---|---|---|
| Follow up / check back ("check how the dog's tail heals", "continue tomorrow") | 40 | 4 |
| One-off reminder ("remind me to book flights") | 8 | 8 |
| Watch until something happens (job posted, listing sold, sale starts, feature ships) | 6 | 0 |
| Recurring ("at the start of workouts", "analyse my training weekly") | 2 | 1 |

Reminders shipped today. Watching-until is a real need nobody asks for because nobody
knows it is possible. The largest group - checking back in a conversation later - has no
support at all. And everything set from chat today lands among the full agents in the
Command Center, with an editor and tool permissions it does not need, and nothing ever
cleans it up.

## Goals

1. Four kinds of **lightweight item**, all set from chat with the `schedule` tool and the
   existing preview-then-confirm flow:
   - **Reminder** - a push at a time (exists; unchanged behaviour).
   - **Check-in** - at a time, Moneypenny asks a question back *in the chat that set it*
     ("How's the tail looking - is the fur growing back?"), so the user replies in context.
   - **Watcher** - checks something on the web periodically and reports in its chat when the
     condition is met, then stops itself ("tell me when the school posts a teacher job").
   - **Recurring** - a regular check or digest that reports in its chat ("every Monday,
     what's for lunch at school this week") - today's chat-created tasks, moved over.
2. **They live with their chat** (Jiri's choice, option A): a header chip in that chat
   shows its active items; results arrive as turns in that chat.
3. **A lighter lane in the Command Center** (Jiri's choice, option C): "From chats", above
   the full agents - one line per item, no editor, no tool permissions.
4. **They clean up after themselves** (see Lifecycle).

## Non-goals

- Editing an item's prompt or tools (cancel and ask again in the chat instead).
- Watchers that need private data (inbox, letters, bank) - only what the read-only web
  tools can see. The model says so when asked.
- Goal mode / long multi-step tasks, once-per-failure alerting for full agents, and the
  Daily Briefing delivering into a chat - separate TODO items.
- A sidebar "Upcoming" list (option B, not chosen).

## Anti-goals (a failure even if it works)

- **More noise.** A watcher or recurring item that pushes when nothing changed. Silent
  runs (`[SILENT]`) stay the default; only real results push.
- **Clutter.** Finished, expired or orphaned items lingering anywhere in the UI.
- **Looking like full agents.** No editor, permissions, budgets or run logs in the
  lightweight UI.
- **Suggestion chips** in empty states (Jiri dislikes them).
- Replacing the liquid-glass look with solid surfaces.

## Decisions

### What they are

- **One table of lightweight items, not agents.** The `reminders` table grows into
  "scheduled items" with a `kind` (reminder | check_in | watcher | recurring), the
  originating `conversation_id` (required), the text/prompt, the schedule (one-off
  instant or cron/interval), `next_run_at`, `expires_at`, `status`, and watcher state
  (last result fingerprint, consecutive quiet runs). *My call* - reminders already live
  there, and the items need behaviour agents don't have (origin chat, expiry, self-stop)
  and lack what agents carry (editor, permissions, own conversation).
- **Nothing to migrate** (checked in production Nov 7 2026: 0 chat-created agents, 0
  reminders). Chat-created recurring agents never recorded their originating chat, so
  any created before this ships cannot be tied to one: the migration deletes agents whose
  description starts "Created from chat" (with their run conversations) and the release
  note says so. `conversation_id` is required for every item - no chatless reminders
  exist to preserve. Re-check the counts right before the migration lands.
- **Model-backed runs reuse the agent run machinery** (tools, the `[SILENT]` marker, cost
  tracking against the user, the daily spend warning) with the always-safe read-only tool
  set - the builder decides how (e.g. an ephemeral agent context) as long as no agent row
  appears in the Command Center's agent list.

### How each kind runs

- **Reminder:** unchanged - the scheduler pushes the text, opening its chat. No turn in the
  chat (*my call*: it asks nothing and reports nothing).
- **Check-in:** the question is **written at creation** from the conversation context
  (the model fills it as the item's text and the preview shows it); at the due time the
  scheduler posts it as an assistant turn in the chat, labelled ("Check-in"), and pushes
  it. No model call at fire time (*my call* - cheap and certain, like reminders). Then done.
- **Watcher:** a model run on its interval, given the watcher's prompt, its end condition
  and the previous result. Replies `[SILENT]` (nothing new: no turn, no push), `[DONE]`
  plus the report (condition met: labelled turn in the chat + push, item done), or a
  report (something changed but not done: turn + push, keeps watching).
  - Interval *(my call)*: the model picks `6h`, `daily` (default) or `weekly` from the
    urgency; nothing more frequent than every 6 hours.
  - Back-off *(my call)*: after 7 consecutive quiet runs the interval doubles, up to
    weekly; any report resets it. Not for watchers with a date-bound end ("until the sale
    on the 28th").
- **Recurring:** today's behaviour (cron in the household timezone, `[SILENT]` honoured),
  but the report is posted as a labelled turn in its chat instead of an agent
  conversation.
- **A delivered turn is an ordinary assistant message** in that chat, so the user's reply
  continues with the conversation as context. Labelled by kind and time
  ("Watcher · found", "Check-in · Fri 18:00").

### Lifecycle (self-cleaning)

- Reminder and check-in: **gone once fired**.
- Watcher: gone when `[DONE]`, or at **expiry - default 30 days** (*my call*) or the date
  the user gave ("until Christmas"); expiry posts a short "Stopped watching: …" turn in
  the chat (no push).
- Recurring: until cancelled; optional end date.
- **A chat's items follow the chat** (Jiri): moving a chat to the trash **suspends** its
  items (nothing runs, nothing shows in the lane); **restoring the chat restores them**;
  deleting it permanently (or the trash purge) deletes them.
  - Archiving behaves like the trash - suspend on archive, restore on unarchive (*my
    call*, by analogy: both are reversible).
  - A one-off (reminder, check-in) whose time passed while suspended is not fired late on
    restore; it is dropped with a short "Missed while this chat was in the trash: …"
    turn (*my call*). A watcher resumes; its expiry date is unchanged.
- Finished items (fired, done, expired, cancelled) are deleted, not kept as history - the
  chat holds the record.
- A watcher whose runs keep failing (tool or model errors) stops after 3 consecutive
  failures with a "Stopped watching - kept failing" turn (*my call*).

### UI

- **Chat header chip** (like the facts chip): "⏰ N" when the chat has active items;
  opens a sheet listing them - kind icon, short name, when / how it ends ("Fri 18:00 ·
  then done", "daily · until found · checked 2h ago"), with cancel, and pause/resume for
  watchers and recurring. Hidden when none.
- **Command Center "From chats" lane** above the agents: one line per active item across
  all chats - icon, name, when, how it ends, its chat (link), cancel. Hidden when empty.
  Chat-created items no longer appear among the agents.
- **Delivered turns** carry a small label (kind · time) above the message text.
- Desktop and mobile (768px breakpoint), both themes; vertical rhythm per the existing
  design rules.

### The tool

- `schedule` gains `kind="check_in"` (date + time + the question) and `kind="watcher"`
  (what to check, the end condition, interval hint, optional until-date). Preview and the
  confirm gate unchanged; previews show how it ends ("…then stops", "until found, at most
  30 days").
- `list` / `pause` / `resume` / `delete` cover all four kinds, scoped to the user.
- Bound in ordinary chats only (not anonymous, not agents) - unchanged.

### Limits

- `SCHEDULE_MAX_ACTIVE_PER_USER` (20) counts all four kinds.
- Watcher and recurring runs count toward the user's spend like any agent run.

## Constraints

- Production daily driver with 4 users; the repo is public (no infra in docs/commits).
- New migration: check the highest number on main right before committing; any
  pending `reminders` rows that exist by then must survive the change.
- New env vars: `src/config.py` default, `.env.example`, the `docs/features/` page.
- Tool changes: `make prompt-snapshots`; evals for check-in and watcher creation (report
  cost).
- UI: tests on desktop and mobile; Linux visual baselines via `/regen-baselines` if a
  visual test changes.
- Multi-worker production (2 gunicorn workers + the scheduler process): no per-process
  state; claim runs atomically like `claim_due_reminders`.

## Left to the builder

- Table/column names and the migration shape (rename vs new table + copy).
- How model-backed runs reuse the executor without an agent row.
- The watcher run prompt wording and how the previous result is passed.
- Chip and lane markup, icons (from the central icon set), and copy.
- How delivered turns are labelled in the data (a message field vs metadata).

## How we'll know it worked

- In a month's sweep, check-ins and watchers are being created and their delivered turns
  get replies.
- No finished or orphaned item is ever visible; the "From chats" lane and chips show only
  live items.
- Watcher pushes are rare and each one carries news.
