# Proposals

The one way Moneypenny asks for a yes. Instead of acting, a tool files a
**proposal**; the reply shows it as a **card**; the user answers on the card or
by replying; the **server** applies exactly what the card showed. Design:
[One approval mechanism](../superpowers/specs/2026-11-09-one-approval-mechanism-design.md)
(step 1 shipped Nov 9 2026: the chat setups; steps 2-5 move agent-run
approvals, deep research, chat deletes and clarifying questions onto it).

## What proposes today

| Kind | Tool | Option | Applies |
|---|---|---|---|
| `schedule_item` | `schedule` (create) | Set it up | stores the reminder / check-in / watcher / recurring check |
| `create_agent` | `create_standing_chat` | Create agent | creates the standing chat and its job |
| `edit_agent` | `edit_standing_chat` in the agent's chat | Apply | applies the settings change |

`edit_standing_chat` in an unattended run still files a `job_approvals` request
(step 2 moves it).

## The record

`proposals` (migration 0086, `src/db/models/proposals.py`): `kind`, `summary`,
`details` (label -> value), 1-4 `options` (label, description, **payload** -
exactly what choosing it applies; never sent to the client), `state`
(`pending`, `approved`, `declined`, `expired`, `superseded`, `failed`),
`chosen`, `result` (what applying did, or why it failed), `resolved_by`
(`button`, `typed`, `system`), `reported` (the agent was told), `request_id`
(the turn that filed it) and `message_id` (the reply that shows it, set when
the reply is saved - `link_proposals` in `chat_save.py`).

Triggers: a change bumps the conversation in the sync change log (another
device re-renders the card); deleting the reply (regenerate, truncate,
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
  409), applies the chosen option, logs **"Proposal resolved"** (`kind`,
  `state`, `resolved_by`, `seconds_open`).
- **Typed answers** (`answer_typed`, run by `prepare_turn` before the agent):
  the whole message, casefolded, trailing punctuation dropped. Yes words
  (`yes`, `ok`, `do it`, `ano`, `jo`, `jasně`, `dobře`, 👍, ...) approve a
  one-option card; `1`-`4` or an option's exact label pick among several (a
  yes then answers nothing); no words (`no`, `not now`, `ne`, `zrušit`, 👎)
  decline. They resolve **every** pending card on the latest reply showing
  any. Any other message expires the conversation's pending cards - the user
  moved on - and a reply that never saved its card (the turn failed) leaves it
  unlinked: it expires the same way. A rerun (regenerate/continue) answers
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
  "Expired - ...". A 409 says the card is no longer open; a network error keeps
  it answerable.
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
