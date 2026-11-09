# One approval mechanism - design

Nov 9 2026. TODO item "One approval mechanism". Status: design, awaiting approval.

## Intent

Moneypenny asks the family for a yes in four different ways today, each with
its own storage, UI and answer path. The same intent - "may I do this?" - should
have one obvious way to be asked and answered (Jiri: "There shouldn't be
different ways of achieving the same outcomes (think Python principles)").
A proposal the user approved must be exactly what happens, enforced by code,
not by the model following a prompt.

## Today (the four mechanisms)

| | Where | Asks with | Answered by | Stored in | Applied by |
|---|---|---|---|---|---|
| A | Chat: `schedule` (reminders, check-ins, watchers, recurring checks), `create_standing_chat`, `edit_standing_chat` in conversation | a written preview in the reply | the user's next message ("yes"), then the model calls the tool again with `confirm=true` | kv, reserved namespace per conversation (`src/agent/tools/pending_gate.py`), expires after the user's next message | the model's confirm call (the gate checks it matches the preview) |
| B | Unattended agent runs: `request_approval` (model-driven), destructive Todoist/Calendar operations (`permission_check._check_destructive_approval`, argument-level, consumed once), writes without the write grant (`_check_write_approval`), `edit_standing_chat` in a run | the run pauses (`ApprovalRequestedException`); an approval card in the agent chat (`render.ts addApprovalRequestMessageToUI`) and in Command Center (`CommandCenter.renderApprovalCard`) | Approve / Reject / Always allow buttons (`src/api/routes/approvals.py`); the agent chat composer is blocked meanwhile (`setInputBlockedForApproval`) | `job_approvals` | approve resumes the job's run, which retries the call and consumes the approval |
| C | Deep research | an offer card with an editable plan, cost estimate, autostart countdown (`web/src/components/messages/research-offer.ts`) | Start (through the chat stream) / No thanks (`PATCH /messages/<id>/research-offer`) | `messages.research = {"offer": ...}` | the start request |
| D | Chat: deleting/archiving tasks, projects, sections or events, ambiguous completes, rescheduling, attendee changes | a prompt rule only (`prompt_texts/productivity.py` "CRITICAL - confirm destructive...") | the model judges the user's reply | nowhere | the model, unchecked |

Problems: the answer differs per mechanism (typed in A and D, buttons in B and
C, typing refused in B); A and D let the model act on the yes; D is enforced by
nothing; "approve" means a different thing in each.

## Goals

1. One record for anything awaiting the user's yes: a **proposal**.
2. One card that shows and answers every proposal, the same in any chat and
   in Command Center.
3. Approving applies the proposal's stored payload on the server. The model
   never re-issues the change after a yes.
4. A typed yes stays possible, as an alias that resolves the same proposal
   (decided by Jiri, Nov 9 2026: "Buttons + typed alias").
5. Destructive Todoist/Calendar changes in chat are gated in code by a
   proposal (decided by Jiri, Nov 9 2026: "Yes, enforce in code").
6. Instrumented (rule A8): every proposal's outcome and time to answer is
   recorded; a check in docs/regular-review.md; a dated re-measure in TODO.md.

## Non-goals

- No new kinds of things that need approval; this unifies the existing ones.
- No approval queue for agent memory edits (decided Oct 26 2026: they write
  inline - see memory `feedback-no-approval-queues-bespoke-integrations`).
- No change to what an agent's grants allow (the write level, "Can change
  things without asking"); only how the remaining yes is asked.
- No suggestion chips or canned replies.

## Anti-goals (a failure even if it works)

- Two ways remain: any of A-D keeps its own storage or its own card.
- A proposal the user approved runs with different arguments than shown.
- A "yes" in a web page, a tool result or the model's own text approves
  anything (prompt injection): only the user's own message or button does.
- A stale proposal (days old, superseded, its chat gone) can be approved.
- Chat gets noisy: a card for every harmless lookup. Only the cases in A-D
  propose.

## The design

### Proposal record

A `proposals` table (one migration) replacing `job_approvals` and the kv
pending gate:

- `id`, `user_id`, `conversation_id`, `message_id` (the reply that shows it;
  set when the reply is saved), `kind`, `options` (JSON, 1-4: each a label, a
  short description and its payload - exactly what choosing it does; plain
  yes/no is one option plus Decline), `chosen` (the option picked), `summary` (plain language, the user's language), `details` (JSON for
  the card body: fields, permissions spelled out, cost estimate), `origin`
  (`chat` or `run`, with `job_id` and `execution_id` for runs), `state`
  (`pending`, `approved`, `declined`, `expired`, `superseded`, `failed`),
  `created_at`, `expires_at` (runs only), `resolved_at`, `resolved_by`
  (`button`, `typed`, `system`), `always_allowed` (bool, B only).
- Kinds: `schedule_item`, `create_agent`, `edit_agent`, `agent_action` (a
  run's request_approval / write / destructive call), `deep_research`,
  `chat_change` (D).
- Existing pending `job_approvals` rows migrate as `agent_action` /
  `edit_agent` proposals; resolved ones migrate for history. Pending kv
  previews are not migrated (they expire after one message anyway).

### Filing a proposal

- **A**: `schedule`, `create_standing_chat`, `edit_standing_chat` (in chat)
  keep validating and building the preview, but file a proposal instead of a
  kv entry. Their `confirm` parameter is removed: the tool's result tells the
  model the card is shown and to wait.
- **B**: `request_approval`, the destructive gate, the write gate and
  `edit_standing_chat` in a run file an `origin=run` proposal and pause the run
  as today. One-time consumption stays, and matching tightens to the full
  call: the payload stores the call's canonical arguments, and only an
  identical call (`call_signature`, `src/agent/tool_loops.py`) consumes the
  approval - so the resumed run cannot run different arguments than the card
  showed (today the write gate matches tool + operation, the destructive gate
  also the target). *My call.*
- **C**: `propose_deep_research` files a `deep_research` proposal; the plan
  is its payload. The card's body is today's plan editor; edits update the
  payload while pending. Autostart (an explicit request) stays: the countdown
  approves it unless the user edits or declines.
- **D**: destructive operations called in chat - exactly the run gate's
  list (`DESTRUCTIVE_OPERATIONS`: Todoist/Calendar deletes and archives, and
  the Rouvy workout delete) - file a `chat_change` proposal instead of
  running; the tool result tells the model to wait. Completes and reschedules
  are not gated (gating every complete would make chat noisy; the prompt rule
  keeps asking about ambiguous ones). All of one turn's destructive calls
  collect into one proposal listing each operation ("Delete these 3 tasks" is
  one card with three lines), applied together. *My call.*

A new proposal of a kind supersedes a pending one of the same kind from an
earlier reply in that conversation (state `superseded`). One reply can carry
several proposals of different kinds (a reminder and a delete).

### Options (decided by Jiri, Nov 9 2026: "Yes, shape now, step 5 later")

The record and card hold 1-4 options from step 1, so a proposal is a choice,
not only a yes. Today's cases mostly have one option (Approve); the run
approval's "Approve once" / "Always allow" become two options. A choice either
applies its payload (a reminder vs a watcher) or - step 5 - only answers a
question: the picked label becomes the user's reply and the turn continues
("which dentist event?"). Options appear only when the model has a real choice
to offer, never as generic suggested replies (no suggestion chips).

### Answering

- **Buttons** on the card: Approve / Not now (and Always allow for an
  `agent_action` on a writable integration the agent holds, as today). One
  endpoint family: `POST /api/proposals/<id>/approve` (body: `always`,
  optional edited payload for `deep_research`), `POST /api/proposals/<id>/decline`.
- **Typed alias, several options**: the option's number or its exact label
  picks it; a typed "yes" resolves nothing (the card stays).
- **Typed alias, one option**: when the user's next message in that conversation is a
  plain yes or no ("yes", "ano", "jo", "ok", "do it", "no", "ne"...; a short
  fixed list per language, matched on the whole trimmed message), the server
  resolves every proposal pending on the latest reply that showed any -
  approve all on "yes", decline all on "no" - before the turn runs
  (`resolved_by=typed`), and the turn's model sees the outcome (decided by
  Jiri, Nov 9 2026: "Approve all on that reply"; to pick one, use its card).
  Any other message leaves nothing approved; the model may still ask "shall
  I?" in text, but only the user resolves.
- Expiry: a pending chat proposal (A, C, D) expires after the user's next
  message that does not answer it, as today's gate. A run proposal keeps
  today's `AGENT_APPROVAL_TTL_HOURS` (24 h, `expires_at`), and the zombie
  cleanup of `waiting_approval` runs stays (`src/db/models/job_runs.py`);
  migrated pending `job_approvals` keep their own expiry. *My call.*
- The agent chat composer is no longer blocked while a run waits (decided by
  Jiri, Nov 9 2026: "Normal reply, run waits"): a typed yes/no resolves the
  run's proposal and only resumes or ends the run - no separate chat turn; any
  other message is a normal chat turn and the paused run keeps waiting on its
  card.

### Applying

On approve the server applies the payload, never the model:

- `schedule_item`, `create_agent`, `edit_agent` (chat): the code paths the
  confirm call runs today, called with the stored payload.
- `agent_action`, `edit_agent` (run): resume the run as today
  (`_approve_job_request`); the gates consume the approved proposal.
- `deep_research`: start the run as the Start button does today.
- `chat_change`: perform the stored Todoist/Calendar operation.

The result lands in the conversation as a short line under the card (done /
failed with the reason), and the model is told on the user's next turn (a
system note, like today's approval resume message). Failure sets `failed` and
the card says so.

### The card

One component replacing the approval card, the offer card and the written
preview: a header with the kind's icon and the summary, a body (fields; tools
it may use with what each can change; the plan editor for deep research; the
exact item for a delete), and the actions. Resolved cards collapse to one line
("Reminder set for Thu 8:00", "Declined", "Expired"). Command Center's "Needs
you" shows the same card for pending **run** proposals only; chat proposals
live in their chat, where their expiry rule makes sense. *My call.* Visual design follows the app
(liquid glass, the release-card typography); desktop and mobile.

### Instrumentation (A8)

`proposals` itself is the data: per kind, the share approved / declined /
expired / superseded / failed, button vs typed, and time to answer. A log line
"Proposal resolved" (kind, state, resolved_by, seconds). Check added to
docs/regular-review.md; re-measure in TODO.md ~2 weeks after the last step
ships (are typed answers common? do chat deletes now wait on cards that
nobody answers?).

### Order (each step ships alone, main stays deployable)

1. The table, the card, the endpoints, the typed alias; migrate A.
2. B: `job_approvals` folds in; the composer unblocks.
3. C: deep research onto proposals.
4. D: destructive chat changes gated.
5. Choices that only answer: clarifying questions and "choose an approach"
   (folds in the TODO item "Clarifying questions with options" from the
   Hermes comparison).

## Constraints

- Public repo; production is used daily: every step behind the full gate,
  deployed alone, with a migration whose rollback works.
- Rules A7 (a What's new post for what users see change - the cards, the
  typed yes in agent chats, deletes now asking) and A8 apply.
- Multi-worker: proposal state lives in the DB, never in process memory.
- Batch mode must match streaming (cards render from the saved reply).

## Left to the builder

- Table and column names, the endpoint shapes beyond the above, how the card
  is composed from existing components.
- The yes/no word lists (Czech and English), kept short and whole-message.
- How each kind's summary is phrased (plain, the user's language).
- Whether `job_approvals` is dropped in step 2 or kept read-only for a while.
