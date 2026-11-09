# One approval mechanism, step 3 - deep research on proposals

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A deep-research offer (and a report's follow-up offer) is a `deep_research` proposal shown on the one proposal card; the offer state leaves `messages.research`.

**Architecture:** The reply's save files the proposal (payload = the plan) on the saved message, as it stores the offer today. Start stays a chat-stream turn ("Start deep research") that names the proposal and the edited plan; `start_plan` claims the proposal. A typed yes resolves it in `prepare_turn` and that same turn becomes the run. No thanks is the shared decline endpoint. Old offers migrate into proposals (production: 3, all decided).

**Tech Stack:** Flask, SQLite (yoyo), LangGraph; TypeScript + Vite + Zustand.

**Spec:** docs/superpowers/specs/2026-11-09-one-approval-mechanism-design.md (C, Applying, The card)

## Global Constraints

- The plan editor, live estimate, the autostart countdown (explicit request + `run_now` only, once per page, any edit pauses it) and the follow-up offer keep their behaviour.
- One record: after this step nothing reads or writes `research.offer` / `research.run.followup` status; `research.run` (the report's run data) stays.
- A chat proposal expires on the user's next message that doesn't answer it (spec Answering) - this replaces "open until superseded".
- `/api/proposals/<id>/approve` refuses `deep_research` (409 "Start it from its card"): starting is a turn.
- Log lines kept (A8): "Deep research offered / started / declined / superseded", plus "Proposal resolved".
- Batch mode never starts research (stream only, as today); batch renders the card.
- A7: What's new only if the user-visible flow changes (expiry on the next message does) - one line in a post.

## Review Focus

1. A typed yes while the offer's turn still streams (turn_running) - must not start a second run.
2. Start on two devices at once - one run; the other card shows "started".
3. An autostart countdown firing after the user typed something else (the card expired) - the start must fail cleanly and the card show expired.
4. A follow-up offer on a report, approved by typing "yes" - the run gets `previous_report`.
5. Rolling migration 0089 back restores the three offers' statuses.

---

### Task 1: `deep_research` kind, filed on save; start/decline through the proposal

**Files:** `src/agent/deep_research/offer.py`, `plan.py`, `src/api/helpers/chat_save.py`, `src/api/helpers/chat_turn.py`, `src/api/schemas/chat.py` (`DeepResearchStart.proposal_id` replaces `offer_message_id`), `src/api/routes/conversation_messages.py` (PATCH research-offer removed), `src/api/routes/proposals.py`, `src/db/models/message.py` (offer queries removed), `migrations/0089_research_offers_to_proposals.py`; tests `tests/unit/test_deep_research_offer.py`, `test_deep_research_save.py`, `tests/integration/test_deep_research_start.py`, `tests/unit/test_migration_0089.py`, e2e server fakes.

**Interfaces (produces):** `KIND = "deep_research"`; payload `{question, context, sub_questions, estimate, rates, autostart, kind: "initial"|"followup", round}`; `start_plan(conv_id, proposal_id, sub_questions, context) -> DeepResearchPlan` (claims pending -> approved with result "Started"; the final plan - `final_sub_questions`, `final_context`, `final_estimate` - is written into the chosen option's payload in the same UPDATE, so no new column); `DeepResearchPlan.offer_message_id` = the proposal's message.

- [ ] Tests: an offer saves a pending `deep_research` proposal on the reply (details: the question); a report's follow-up files one on the report message; a new offer supersedes an open one; start with the edited plan claims it and returns the plan; a second start is a validation error ("already started"); decline via `/api/proposals/<id>/decline` logs "Deep research declined"; approve via the button endpoint is 409; a typed "yes" on the offer makes the turn a research run with the stored plan (stream), and on a follow-up passes `previous_report`; a typed yes while a turn runs does not start one.
- [ ] Implement; remove the old offer status paths and `find_open_research_offers` / `decide_research_offer`.
- [ ] Migration 0089: each message's `research.offer` / `research.run.followup` becomes a proposal (offered->pending linked, started->approved, declined->declined, superseded->superseded), then the key is dropped from the JSON; rollback writes them back. Test both ways.
- [ ] `make openapi && make types`; backend suite green; commit `feat(research): deep-research offers are proposals`.

### Task 2: the card

**Files:** `web/src/components/messages/research-offer.ts` (becomes the `deep_research` body + actions renderer), `proposal-card.ts` (delegates the kind's body/actions; collapsed line "Researched N questions" with the report link), `web/src/core/deep-research.ts` (start by proposal id; decline via the proposals API), `batch-send.ts`, `render.ts`/startup wiring, CSS (`research.css` -> rules for `.proposal-card--deep-research`, F7); tests `web/tests/component/research-offer.test.ts`, `web/tests/e2e/deep-research.spec.ts`, visual `deep-research.visual.ts` (darwin + linux regen).

- [ ] Component tests: the card shows the editor, estimate updates, Start sends the proposal id and plan, countdown starts once on a live reply, decline calls the shared endpoint, a started card collapses with its report link, an expired one says so.
- [ ] Implement; E2E green on desktop and mobile; screenshots reviewed (vertical rhythm).
- [ ] Commit `feat(web): the deep-research offer is the proposal card`.

### Task 3: docs, review check, re-measure, What's new

- [ ] `docs/features/deep-research.md`, `proposals.md`; regular-review check (offers by outcome from `proposals`); TODO re-measure; announcement line if the expiry change shows. Commit `docs(research): ...`.
