# One approval mechanism, step 1: proposals for chat setups - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One proposal record, card and answer path; the chat setups (`schedule`, `create_standing_chat`, `edit_standing_chat` in conversation) move onto it off the kv pending gate.

**Architecture:** A `proposals` table (DB layer) holds what awaits the user's yes, with 1-4 options each carrying the exact payload. `src/agent/proposals.py` files proposals from tools, answers them (button or typed), and applies the chosen option through a per-kind registry of apply functions that live with each tool. The turn path resolves typed answers before the agent runs and tells the agent the outcome; the save path links the turn's proposals to the reply; the web renders one card per proposal.

**Tech Stack:** Python 3 / Flask / APIFlask schemas (Pydantic), SQLite via yoyo migrations, LangGraph tools; vanilla TypeScript + Zustand; Vitest, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-09-one-approval-mechanism-design.md`

## Global Constraints

- Public repo: no hostnames or infra in tracked files or commits (S9).
- Main stays deployable; every commit passes `make lint` + `E2E_PORT=8042 make pre-commit`; heavy jobs under `nice -n 10` + `caffeinate -i`; check exit codes directly.
- Migration number: the next free on `main` (0086 today) - re-check right before committing.
- Imports point down: routes -> helpers -> agent -> services -> db -> utils. Apply functions live in the agent layer.
- Multi-worker: all proposal state in the DB.
- Batch mode matches streaming: cards render from the saved reply in both.
- UI copy is English (app chrome); proposal summaries follow the user's language (the model writes them).
- Rule A7: a What's new post (cs + en) in the step's last commit. Rule A8: "Proposal resolved" log line, a regular-review check, a dated re-measure in TODO.md.
- Kinds in this step: `schedule_item`, `create_agent`, `edit_agent`. Each has exactly one option. Option labels: `Set it up` (schedule_item), `Create agent` (create_agent), `Apply` (edit_agent). Decline label: `Not now`.
- Typed yes words (whole trimmed message, casefolded, trailing `.!` and spaces stripped): `yes`, `y`, `yeah`, `yep`, `sure`, `ok`, `okay`, `do it`, `go ahead`, `ano`, `jo`, `jj`, `jasně`, `dobře`, `souhlasím`, `potvrzuji`, `👍`. Typed no words: `no`, `nope`, `not now`, `cancel`, `ne`, `nechci`, `zrušit`, `👎`. With several options, `1`-`4` or an option's exact label (casefolded) picks it, and a yes word resolves nothing.

## Review Focus

1. **Two taps at once (double tap, two devices)** - the option applies once; the second request gets 409 and the card shows the first outcome. Test in Task 2 (`test_resolve_applies_once_under_a_race`).
2. **The option can no longer apply** (the reminder time passed, the item cap is reached, the agent name was taken meanwhile) - state `failed`, the card shows the reason, nothing half-created. Test in Task 3 (`test_approving_a_past_reminder_fails_cleanly`, `test_approving_a_taken_agent_name_fails_cleanly`).
3. **A yes inside a longer message** ("yes but at 9") - not an answer: the proposal expires and the model handles the message as a turn. Test in Task 2 (`test_a_qualified_yes_is_not_an_answer`).
4. **A proposal whose reply was never saved** (the turn errored) - it has no card and expires at the next user message; the API refuses to resolve it. Test in Task 4 (`test_proposal_of_a_failed_turn_expires`).
5. **The reply carrying a pending proposal is regenerated, truncated or deleted** - the proposal expires; it can never be approved from a message that no longer exists. Test in Task 4 (`test_regenerate_expires_the_replys_proposal`).

---

### Task 1: The proposals table and its DB model

**Files:**
- Create: `migrations/0086_proposals.py`, `src/db/models/proposals.py`
- Modify: `src/db/models/__init__.py` (mixin), `src/db/models/dataclasses.py` (`Proposal`), `vulture_whitelist.py` if TypedDict keys need it
- Test: `tests/unit/test_proposals_db.py`, `tests/integration/test_migration_0086.py`

**Interfaces:**
- Produces:
  - Table `proposals(id TEXT PK, user_id, conversation_id, message_id NULL, request_id, kind, summary, details JSON, options JSON, state TEXT DEFAULT 'pending', chosen INTEGER NULL, result TEXT NULL, resolved_by TEXT NULL, reported INTEGER DEFAULT 0, created_at, resolved_at NULL)`; indexes on `(conversation_id, state)` and `message_id`. Sync triggers on insert/update bump the conversation (as `0061_add_sync_change_log.py` `_bump`). The migration also deletes kv rows in namespaces `schedule_pending`, `standing_create_pending`, `standing_pending`.
  - `@dataclass Proposal` with those fields; `ProposalOption = TypedDict(label: str, description: str, payload: dict[str, object])`; `ProposalState = Literal["pending","approved","declined","expired","superseded","failed"]`.
  - `ProposalsMixin`: `create_proposal(proposal: Proposal) -> Proposal`, `get_proposal(proposal_id: str, user_id: str) -> Proposal | None`, `proposals_for_messages(message_ids: list[str]) -> dict[str, list[Proposal]]`, `pending_proposals(conversation_id: str) -> list[Proposal]`, `claim_proposal(proposal_id: str, state: ProposalState, chosen: int | None, resolved_by: str) -> bool` (UPDATE ... WHERE state='pending'; True for the one winner), `finish_proposal(proposal_id: str, state: ProposalState, result: str) -> None`, `link_proposals(request_id: str, message_id: str) -> None`, `expire_proposals(conversation_id: str, message_id: str | None = None) -> int`, `unreported_proposals(conversation_id: str) -> list[Proposal]`, `mark_reported(ids: list[str]) -> None`.

- [ ] **Step 1: Failing tests** - `test_create_and_get_round_trips_options`, `test_claim_is_won_once` (two claims: True then False), `test_link_sets_the_reply_for_a_request`, `test_expire_by_conversation_and_by_message`, `test_proposals_for_messages_groups_them`, `test_a_proposal_change_bumps_the_conversation` (sync change-log seq grows); `test_rollback_0086` (table and triggers gone).
- [ ] **Step 2:** Run them: FAIL (no table / no module).
- [ ] **Step 3:** Migration + mixin + dataclass as above.
- [ ] **Step 4:** Run: PASS; `make lint` clean (Any ratchet, vulture).
- [ ] **Step 5:** Commit `feat(db): proposals - one record for anything awaiting the user's yes`.

### Task 2: Filing, answering and applying (agent layer)

**Files:**
- Create: `src/agent/proposals.py`
- Test: `tests/unit/test_proposals.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `register_kind(kind: str, apply: Callable[[Proposal, ProposalOption], str]) -> None` - `apply` returns the result line or raises `ProposalFailed(reason: str)`.
  - `file_proposal(kind: str, summary: str, details: Mapping[str, object], options: list[ProposalOption]) -> Proposal` - reads user, conversation and request id from the contextvars (`get_conversation_context`, `get_current_request_id`); a pending proposal of the same kind filed by the same request becomes `superseded` (parity with today's one preview per namespace).
  - `resolve(proposal: Proposal, choice: int | None, by: Literal["button","typed"]) -> Proposal` - `choice=None` declines; claims (409-able: raises `ProposalNotPending`), applies, finishes `approved` with the result or `failed` with the reason; logs "Proposal resolved" (`kind`, `state`, `resolved_by`, `seconds_open`).
  - `typed_answer(text: str, options: list[ProposalOption]) -> int | None | Literal["no-answer"]` - option index, `None` for a no, `"no-answer"` otherwise, per the Global Constraints word lists.
  - `answer_typed(conversation_id: str, text: str) -> list[Proposal]` - resolves every pending proposal on the latest reply carrying any (each by its own typed_answer), returns them; when the text is no answer, expires every pending proposal in the conversation and returns `[]`.
  - `turn_note(conversation_id: str) -> str | None` - for unreported resolved proposals: one guidance line each ("The user approved: <summary> - <result>" / declined / it failed: <reason> / expired), marks them reported.

- [ ] **Step 1: Failing tests** - `test_typed_yes_words_cs_and_en`, `test_typed_no_words`, `test_a_qualified_yes_is_not_an_answer` ("yes but at 9" -> "no-answer"), `test_number_or_label_picks_among_options`, `test_yes_resolves_nothing_with_several_options`, `test_resolve_applies_the_chosen_payload`, `test_resolve_applies_once_under_a_race` (two threads, one apply call, one ProposalNotPending), `test_apply_failure_marks_failed_with_reason`, `test_a_second_proposal_of_a_request_supersedes`, `test_answer_typed_resolves_all_on_the_latest_reply`, `test_a_non_answer_expires_pending`, `test_turn_note_reports_once`.
- [ ] **Step 2:** Run: FAIL (no module).
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run: PASS; lint clean.
- [ ] **Step 5:** Commit `feat(agent): proposals - file, answer by button or typed yes, apply what was shown`.

### Task 3: The chat setups file proposals (mechanism A)

**Files:**
- Modify: `src/agent/tools/scheduling.py`, `src/agent/tools/standing_create.py`, `src/agent/tools/standing_settings.py`; delete `src/agent/tools/pending_gate.py`; prompt texts mentioning `confirm=true` (grep `src/agent/prompt_texts` and tool docstrings)
- Modify evals: `evals/cases/schedule_reminder_confirm.yaml` (seed a proposal instead of kv; new harness field `proposals`), the `*_preview.yaml` cases (expect the proposal filed, no `confirm`), `evals/run.py` (seed `proposals`)
- Test: port `tests/unit/test_scheduling*.py`, `tests/unit/test_standing_create*.py`, `tests/unit/test_standing_settings*.py` (grep for `confirm=` / `pending_gate`)

**Interfaces:**
- Consumes: Task 2 (`file_proposal`, `register_kind`).
- Produces: the `confirm` parameter is gone from all three tools. Each validates exactly as today, then `file_proposal(...)` with one option whose payload is today's pending spec, and returns: `"PROPOSAL shown to the user as a card (<label> / Not now). Nothing is set up yet: say in a sentence what you proposed; they approve on the card or by replying yes."` Apply functions registered at import: `apply_schedule(proposal, option) -> str` (today's `_confirm` minus the expired/unanswered checks: the past-time and cap refusals raise `ProposalFailed`), `apply_create_agent(...)` (today's `_confirm` body; IntegrityError -> `ProposalFailed`), `apply_edit_agent(...)` (`apply_standing_changes` + `_describe`). `edit_standing_chat` in an unattended run is unchanged (step 2 moves it).

- [ ] **Step 1: Failing tests** - `test_schedule_create_files_a_proposal_and_stores_nothing`, `test_approving_creates_exactly_the_previewed_item`, `test_approving_a_past_reminder_fails_cleanly`, `test_approving_at_the_item_cap_fails_cleanly`, `test_create_standing_chat_files_a_proposal`, `test_approving_a_taken_agent_name_fails_cleanly`, `test_edit_standing_chat_in_chat_files_a_proposal`, `test_injection_in_text_is_still_refused_before_filing`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement; remove `pending_gate.py` and every `confirm` path; update docstrings, prompts, eval cases.
- [ ] **Step 4:** Run the ported tool tests + `make test`: PASS.
- [ ] **Step 5:** Commit `feat(agent): reminders, new agents and agent settings ask with a proposal card`.

### Task 4: The turn path - typed answers, the outcome note, linking the reply

**Files:**
- Modify: `src/api/helpers/chat_turn.py` (`prepare_turn`: after the user message is saved and not a rerun -> `answer_typed`; `TurnContext._agent_text` appends `turn_note` like `lost_actions_note`), `src/api/helpers/chat_save.py` (after the reply is saved: `db.link_proposals(request_id, message_id)`), message delete / truncate / regenerate paths (`src/api/routes/conversation_messages.py`, the rerun in `chat_turn._resolve_rerun`: `db.expire_proposals(conv_id, message_id)` for the removed replies), `src/api/utils.py` (`add_proposals(data, msg)` beside `add_research`, batched via `proposals_for_messages` in `serialize_messages_for_response`), `src/api/helpers/stream_finalize.py` + `src/api/routes/chat.py` (the done event and the batch response carry the reply's `proposals`), `src/api/schemas/chat.py` (`ProposalResponse`: id, kind, summary, details, options (label, description), state, chosen, result)
- Test: `tests/integration/test_proposals_turns.py`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: `MessageResponse.proposals: list[ProposalResponse] | None`, the same on the stream `done` event and `ChatBatchResponse`; payloads never leave the server.

- [ ] **Step 1: Failing tests** (streaming and batch both, as the repo's E2E fake allows - integration through the routes with the agent mocked to call `file_proposal`): `test_the_reply_carries_its_proposal`, `test_typed_yes_approves_before_the_turn_and_the_agent_hears_it`, `test_a_non_answer_expires_the_proposal`, `test_proposal_of_a_failed_turn_expires`, `test_regenerate_expires_the_replys_proposal`, `test_history_reload_shows_resolved_state`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement; `make openapi` + `make types`.
- [ ] **Step 4:** Run: PASS.
- [ ] **Step 5:** Commit `feat(chat): replies carry their proposals; a typed yes answers them before the turn`.

### Task 5: Approve and decline endpoints

**Files:**
- Create: `src/api/routes/proposals.py`, `src/api/schemas/proposals.py`
- Modify: `src/api/routes/__init__.py`
- Test: `tests/integration/test_routes_proposals.py`

**Interfaces:**
- Produces: `POST /api/proposals/<id>/approve` (body `{choice: int = 0}`) and `POST /api/proposals/<id>/decline` -> `ProposalResponse`; 404 for another user's or an unknown id, 409 when not pending (expired, resolved, superseded, or no reply linked), refused in a read-only conversation (`refuse_if_read_only`), rate-limited like the conversation routes.

- [ ] **Step 1: Failing tests** - `test_approve_applies_and_returns_the_result`, `test_decline`, `test_second_approve_is_409`, `test_unlinked_proposal_is_409`, `test_other_users_proposal_is_404`, `test_choice_out_of_range_is_400`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement; `make openapi` + `make types`.
- [ ] **Step 4:** Run: PASS.
- [ ] **Step 5:** Commit `feat(api): approve or decline a proposal`.

### Task 6: The proposal card (web)

**Files:**
- Create: `web/src/components/messages/proposal-card.ts`, `web/src/api/proposals.ts`, `web/src/styles/components/proposals.css` (imported in `main.css`; `.message`-prefixed rules go in `messages.css`, rule F7)
- Modify: `web/src/components/messages/render.ts` (render `message.proposals` under the content, live appends and history), `web/src/core/stream-done.ts` (attach the done event's proposals), `tests/e2e_server/fixture_routes.py` (`POST /test/seed-proposal`: a `schedule_item` proposal on a seeded assistant reply)
- Test: `web/tests/unit/proposal-card.test.ts`, `web/tests/e2e/proposals.spec.ts` (desktop + mobile)

**Interfaces:**
- Consumes: Tasks 4-5.
- Produces: `renderProposalCard(proposal: Proposal, actions: ProposalActions) -> HTMLElement`; `ProposalActions = { approve(id: string, choice: number): Promise<Proposal>; decline(id: string): Promise<Proposal> }` wired at startup (F1).

Card: header (icon by kind, summary), body (details: label/value rows; tools listed with what each can change), actions (one primary button per option with its label, `Not now`). Resolved: one line - approved: the result; declined: "Not now"; expired: "Expired"; failed: the reason with a warning tone. Buttons disable while a request runs; a 409 re-fetches the conversation's state. Visual: the app's tokens, liquid glass surfaces as elsewhere, the release-card typography; desktop and mobile (768px).

- [ ] **Step 1: Failing tests** - unit: `renders the summary, details and one button per option`, `approve calls the action and collapses to the result`, `failed shows the reason`, `a 409 shows the server's state`; E2E: `approve on the card sets the reminder` (seeded proposal -> click -> result line), `typing yes approves it` (seeded proposal -> send "ano" -> card resolved).
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement; `make build`; review screenshots desktop + mobile, dark + light.
- [ ] **Step 4:** Run unit + `E2E_PORT=8042 make test-fe-e2e`: PASS.
- [ ] **Step 5:** Commit `feat(web): the proposal card - one way to answer what Moneypenny asks`.

### Task 7: Docs, What's new, instrumentation, gate, deploy

**Files:**
- Create: `docs/features/proposals.md`; `announcements/YYYY-MM-DD-cards-for-setups.md` (cs + en: reminders, new agents and agent changes now ask with a card; tap or reply yes)
- Modify: `docs/README.md` (index), `docs/features/agents.md` (the pending gate section -> proposals), `docs/regular-review.md` (Proposals: per kind approved / declined / expired / failed, button vs typed, median seconds to answer, from `proposals`), `TODO.md` (re-measure ~2 weeks after deploy; the One approval mechanism item notes step 1 done, steps 2-5 left)

- [ ] **Step 1:** Write the docs and the post; `test_every_repo_announcement_is_valid` passes.
- [ ] **Step 2:** `E2E_PORT=8042 caffeinate -i nice -n 10 make pre-commit`: exit 0.
- [ ] **Step 3:** Commit `docs(proposals): feature page, review check, re-measure, What's new`.
- [ ] **Step 4:** Final whole-branch review (fresh reviewer, most capable model), one fix pass.
- [ ] **Step 5:** Deploy, health check, then counts-only check of `proposals` in production after a day.
