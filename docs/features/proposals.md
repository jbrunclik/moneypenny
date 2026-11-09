# Proposals

The one way Moneypenny asks for a yes. Instead of acting, a tool files a
**proposal**; the reply shows it as a **card**; the user answers on the card or
by replying; the **server** applies exactly what the card showed. Design:
[One approval mechanism](../superpowers/specs/2026-11-09-one-approval-mechanism-design.md)
(step 1 shipped Nov 9 2026: the chat setups; step 2 agent-run approvals,
step 3 deep research, step 4 chat deletes, step 5 clarifying questions).

## What proposes today

| Kind | Tool | Option | Applies |
|---|---|---|---|
| `schedule_item` | `schedule` (create) | Set it up | stores the reminder / check-in / watcher / recurring check |
| `create_agent` | `create_standing_chat` | Create agent | creates the standing chat and its job |
| `edit_agent` | `edit_standing_chat` in the agent's chat | Apply | applies the settings change |
| `deep_research` | `propose_deep_research` (filed when the reply saves) | Start | the run is the turn: Start sends it with the edited plan, a typed yes on the stream makes that turn the run ([deep-research.md](deep-research.md)) |
| `chat_change` | a delete or archive in a chat turn (Todoist, Calendar, Rouvy) - held by the gate | Delete / Archive | performs each stored call through its tool ([below](#chat-changes-step-4-nov-9-2026)) |
| `question` | `ask_choice` | its 2-4 options | nothing: the pick is the user's reply (a tap sends the label as their message) - [below](#questions-step-5-nov-9-2026) |

`edit_standing_chat` in an unattended run still files a `job_approvals` request
(step 2 moves it).

## Run cards (step 2, Nov 9 2026)

An unattended run's request for a yes is a proposal with `origin = 'run'`
(`job_id`, `execution_id`, `expires_at`, `consumed`; migration 0088 folded
`job_approvals` in). The write and destructive gates file the blocked call's
card - `agent_action`, payload `{tool, args, signature}`, options Approve (+
Always allow for a held writable tool) - and pause the run after the round
(several gated calls in a round: several cards, one pause);
`request_approval` files an unbound one; `edit_standing_chat` in a run an
`edit_agent` one. The answer resumes or ends that run
(`src/agent/run_approvals.py`): see [agents.md](agents.md). A chat
message never expires a run card (only its 24 h `expires_at`); a typed
answer in the agent's chat is **answer-only** - the batch response and the
stream's `done` carry `answer_only` and `answered_proposals` and no reply
(`src/api/helpers/answer_only.py`). Command Center shows the same card under
the agent's name.

## Chat changes (step 4, Nov 9 2026)

In a chat turn, a call in the run gate's list (`DESTRUCTIVE_OPERATIONS` in
[permission_check.py](../../src/agent/tools/permission_check.py): Todoist
delete_task / delete_project / delete_section / archive_project, Calendar
delete_event, the Rouvy delete) does not run.
`check_autonomous_permission` returns `hold_destructive_call()`'s card text
([chat_changes.py](../../src/agent/chat_changes.py)) and the tool answers with
it. Completes, reschedules and attendee changes still run at once; the prompt
asks about the ambiguous ones in text. The card:
- One per turn: the turn's calls collect into its `chat_change` proposal
  (`turn_proposal` / `extend_proposal`, under a lock, because a round's calls
  run in parallel).
- One row per item, named by the integration: Todoist `item_name`, Calendar
  `event_label`, Rouvy `workout_name`. A failed lookup shows the id.
- The payload is `{"calls": [{tool, args, item}]}`, with the full arguments
  (`call_arguments`).

Approving performs each call through its tool as the card's user, with the
hold bypassed. The result says what was done: "Done - task “Buy milk”",
"Done 1 of 2 - not done: ...". Nothing done means `failed`. A log line
"Chat change applied" records calls and failed. The prompt
(`prompt_texts/productivity.py`) tells the model to call deletes right away
and say what waits for the user's OK, never that it is done.

## Questions (step 5, Nov 9 2026)

`ask_choice(question, options)` ([ask_choice.py](../../src/agent/tools/ask_choice.py))
files a `question` card with 2-4 options. Its options only answer.
- **Refused options:** duplicates, labels over 60 characters, a plain yes/no
  word (`is_answer_word`) or a bare number. Those could not be told apart
  from a typed answer.
- **The tool result:** it tells the model to end with the question in one
  sentence.
- **A tap** sends the option's label as the user's own message
  (`ProposalActions.reply` -> `sendUiMessage`). The card shows the pick at
  once.
- **Typing** the label answers it the same way (not its number: "2" may be the
  user's own answer). A tap on a card under an older reply (answered elsewhere
  meanwhile) sends nothing. The turn runs
  normally; the agent hears "The user picked for “<question>”: <label>"
  (per-kind outcome lines, `register_kind(outcomes=...)`).
- **A reply in the user's own words** closes it ("Answered in the chat"). The
  card has no Not now.
- **Scope:** bound in every chat except the planner, never for agents. It is
  not for suggested follow-ups (no suggestion chips). The eval cases are
  `ask_choice_real_fork` and `ask_choice_not_for_clear_requests`.

## The record

`proposals` (migration 0086, `src/db/models/proposals.py`): `kind`, `summary`,
`details` (label -> value), 1-4 `options` (label, description, **payload** -
exactly what choosing it applies; never sent to the client), `state`
(`pending`, `applying`, `approved`, `declined`, `expired`, `superseded`,
`failed`),
`chosen`, `result` (what applying did, or why it failed), `resolved_by`
(`button`, `typed`, `system`), `reported` (the agent was told), `request_id`
(the turn that filed it) and `message_id` (the reply that shows it, set when
the reply is saved - `link_proposals` in `chat_save.py`).

Triggers: a change to what a device shows (state, choice, result, its reply;
0087 - not marking it reported) bumps the conversation in the sync change log
(another device re-renders the card); deleting the reply (regenerate, truncate,
delete) expires its open cards; deleting the conversation (trash purge,
permanent delete) deletes its proposals and their payloads.

## Filing, answering, applying

`src/agent/proposals.py`:

- `file_proposal(kind, summary, details, options)` - from a tool; reads the
  conversation, user and request from the contextvars. A newer proposal of
  the same kind from the same turn supersedes the older (one preview per kind,
  as before). The tool returns `card_shown(proposal)`: the card's content, and
  "say in one sentence what you proposed".
- `register_kind(kind, apply)` - each tool module registers its apply
  function; `apply` returns the result line or raises `ProposalFailedError`
  (time passed, item cap, name taken, agent gone) - the card shows the reason
  and nothing is half-created.
- `resolve(proposal, choice, by)` - claims the pending proposal (one winner:
  two taps or devices apply once, the other gets `ProposalNotPendingError` ->
  409) as `applying`, applies the chosen option, records `approved` or
  `failed`, logs **"Proposal resolved"** (`kind`, `state`, `resolved_by`,
  `seconds_open`). A claim the worker never finished (it died mid-apply) is
  failed as "Interrupted..." at the next turn start once older than
  `APPLY_STALE_AFTER` (2 min, `fail_stale_applying`) - never a false "done".
- Apply functions keep their own checks atomic where two cards can race: the
  scheduled-item cap is checked inside the insert (`add_item_capped`).
- **Typed answers** (`answer_typed`, run by `prepare_turn` before the agent):
  the whole message, casefolded, trailing punctuation dropped. Yes words
  (`yes`, `ok`, `do it`, `ano`, `jo`, `jasně`, `dobře`, 👍, ...) approve a
  one-option card; `1`-`4` or an option's exact label pick among several (a
  yes then answers nothing - unless the kind registered `yes_is_first`: a
  run card's yes is Approve, Always allow its `2`); no words (`no`, `not now`, `ne`, `zrušit`, 👎)
  decline. They resolve **every** pending card on the latest reply showing
  any. Any other message expires the conversation's pending cards - the user
  moved on - and a reply that never saved its card (the turn failed) leaves it
  unlinked: it expires the same way, except while another turn is live in the
  conversation (a send with attachments is not steering): the cards that turn
  filed are not shown yet and stay. A rerun (regenerate/continue) answers
  nothing. A tap that wins the race against a typed answer is skipped, not an
  error.
- **Only the user's typing answers.** An app-sent message - an artifact's
  button (`mp:send`) or the claim card's - carries `app_sent: true`
  (`sendAppMessage` in `core/messaging.ts`) and only expires open cards, so a
  reply can never approve its own card through an artifact. Edit-and-resend is
  typed. Interjections and steering go to the running turn, not
  `prepare_turn`, so they answer nothing either.
- **The agent hears the outcome** on its next turn: `turn_note` adds one line
  per unreported resolved proposal ("The user approved: ... - <result>") to the
  turn's `[SYSTEM GUIDANCE]` (with the lost-actions note), then marks them
  reported. A rerun also hears everything resolved since its user message
  again: a typed yes applied the card, the model call failed, and the
  regenerate must not file the card a second time.

## API and client

- `POST /api/proposals/<id>/approve` (`{choice: 0}`) and `.../decline` ->
  `ProposalResponse` (`src/api/routes/proposals.py`, on `conversations.api`).
  404 for another user's or an unknown id; 409 (with the current proposal in
  `details`) when answered, expired, superseded or not yet shown under a saved
  reply; 400 for a choice out of range.
- Replies carry `proposals` (superseded ones left out) on loaded messages, the
  stream `done` event, the batch response and stream resume; `details` go as
  an ordered list of `{label, value}` rows (JSON objects lose their order).
- The card (`web/src/components/messages/proposal-card.ts`, styles in
  `proposals.css`): an icon tile by kind and the summary, label/value rows, a
  primary button per option and **Not now**. Resolved, it collapses to one
  line: the result, "Couldn't do it: <reason>", "Not now - ...", or
  "Expired - ...", or "Setting it up - ..." while applying. A 409 shows the
  answer that won (the server sends the current card in the error's
  `details.proposal`); a network error keeps it answerable.
- A typed yes resolves an earlier reply's card on the server: after a turn in
  a conversation that showed an open card, the client runs the external-changes
  merge (`core/proposal-sync.ts`, `patchProposals` in `remote-merge.ts`), which
  also re-renders cards answered on another device.

## Measuring (rule A8)

From `proposals` (counts only): per kind, the share approved / declined /
expired / failed, button vs typed (`resolved_by`), and the median seconds to an
answer (`resolved_at - created_at`). The "Proposal resolved" log line carries
the same per answer. Check in [regular-review.md](../regular-review.md);
re-measure in TODO.md.

## Testing

- `tests/unit/test_proposals_db.py`, `tests/integration/test_migration_0086.py`
  - storage, the claim, the triggers, the rollback.
- `tests/unit/test_proposals.py` - typed answers, resolve (incl. the race),
  supersede, expiry, the turn note.
- The tool tests (`test_schedule_tool.py`, `test_standing_create.py`,
  `test_standing_settings.py`) approve the card they filed.
- `tests/integration/test_proposals_turns.py` (batch, stream, history, typed
  yes, expiry, failed turn, deleted reply), `test_routes_proposals.py`.
- `web/tests/unit/proposal-card.test.ts`, `proposal-sync.test.ts`;
  `web/tests/e2e/proposals.spec.ts` (desktop + mobile: the button and a typed
  "ano"; `POST /test/seed-proposal`).
- Evals: the `*_preview` cases (the tool files the card) and
  `schedule_reminder_confirm` (a seeded card answered by "Ano." - the harness
  runs `answer_and_note` like the chat route).
