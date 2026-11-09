# One approval mechanism, step 2: agent-run approvals become proposals - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `job_approvals` folds into `proposals`: an unattended run that needs a yes files a run proposal, the same card answers it in the agent's chat and in Command Center, the agent chat's composer unblocks, and an approved change can only run with the exact arguments the card showed.

**Architecture:** Proposals gain an origin (`chat` / `run`), the run's job and execution, and an expiry. The write and destructive gates stop telling the model to call `request_approval`: they file the proposal themselves from the blocked call (its tool, its full arguments, a plain-language summary) and pause the run. Approving resumes the run, and only a call identical to the one shown (`call_signature`) consumes the approval. `request_approval` stays for actions no gate covers. A typed yes/no in the agent's chat answers the run's card and resumes or ends the run with no chat turn of its own (the run's report is the reply).

**Tech Stack:** as step 1.

**Spec:** `docs/superpowers/specs/2026-11-09-one-approval-mechanism-design.md` (Answering, Applying, Order step 2; decided: "Normal reply, run waits").

## Global Constraints

- As step 1 (public repo, gate per commit range, migration numbering, layering, multi-worker, batch = stream, A7, A8).
- Run proposals expire after `AGENT_APPROVAL_TTL_HOURS` (24 h) via `expires_at`; chat messages never expire them. The zombie cleanup of `waiting_approval` runs stays.
- Kinds added: `agent_action` (a gated write/destructive call, or `request_approval`), and `edit_agent` with origin `run`. Options: `Approve`, plus `Always allow <Tool> changes` for a write the job holds the tool for (today's `always`). Decline: `Not now`.
- No chat turn for a typed answer to a run card: the user message is saved, the run resumes (or ends) in the background, and the client shows the run's report when it lands.

## Review Focus

1. **The resumed run re-issues the call with different arguments** (a different task text, another event) - it must not consume the approval; it files a new card (the run pauses again). Test in Task 2.
2. **The approval arrives after the run proposal expired** (24 h) - 409; the waiting run is closed; the agent can ask again next run. Test in Task 3.
3. **A typed "ano" in an agent chat while the run's card is pending** - resumes exactly that run once; no extra agent reply; a second "ano" answers nothing. Test in Task 4.
4. **Two runs of the same job each paused** (the scheduler and a manual Run) - each card resumes its own execution. Test in Task 2.
5. **Migrated pending job_approvals** - each shows as a card under its approval message and approving it resumes the run as before. Test in Task 1.

---

### Task 1: Run proposals in the schema; pending job_approvals migrate

- Migration 0088: `proposals` gains `origin TEXT NOT NULL DEFAULT 'chat'`, `job_id`, `execution_id`, `expires_at`; pending (and approved-unconsumed) `job_approvals` copy in as `origin='run'` proposals (`kind` `edit_agent` for `edit_standing_chat`, else `agent_action`; payload from `tool_args`; `message_id` = the approval message whose content carries the approval id). `job_approvals` stays read-only for one release (dropped in a later migration).
- DB: `pending_run_proposals(user_id) -> list[Proposal]`, `has_pending_run_proposal(job_id) -> bool`, `consume_run_approval(job_id, signature) -> bool` (approved, unexpired, identical signature; atomically marks it consumed), `expire_run_proposals(now) -> int`.
- `expire_proposals` never touches `origin='run'`.
- Tests: migration copies a pending approval and links its message; rollback; consumption by signature only; chat messages leave run cards alone.

### Task 2: The gates file the card from the real call

- `permission_check`: a write without the write level, or a destructive operation, with no consumable approval files an `agent_action` run proposal - payload `{tool, args, signature}`, summary in words (tool, operation, the key fields), options `Approve` (+ `Always allow` for a write) - and raises `ApprovalRequestedException(proposal_id, ...)`. `ApprovalRequiredError` (the "call request_approval" text) goes.
- `request_approval` files an unbound `agent_action` (no signature: it only pauses for consent; nothing consumes it). `edit_standing_chat` in a run files `edit_agent` with origin `run`.
- `record_approval_request` posts a plain assistant line ("Waiting for your approval below.") and links the proposal to it; the push stays.
- Apply (run origin): `agent_action` -> close the waiting execution, add the "[Action approved: ...]" user message naming the exact call to re-issue, resume with `run_job_now` (as `_approve_job_request`, in a background thread); `Always allow` also grants `<tool>:write`; `edit_agent` (run) -> apply the change, close the execution, no rerun. Decline -> close the execution as rejected, add "[Action rejected: ...]".
- Tests: a gated write files a card and pauses; approving and re-issuing the identical call runs it once; a different call files a new card; two paused executions resume their own; Always allow grants the write level only for a held tool.

### Task 3: Expiry and the jobs API

- The scheduler's sweep expires run proposals past `expires_at` and closes their waiting executions (the zombie cleanup's path); the TTL setting keeps its name.
- `/api/approvals` routes are removed; `PendingApprovalsResponse` and the jobs responses' `pending_approvals` / `has_pending_approval` / `jobs_waiting` come from run proposals (`proposal_to_response` + the job's name). `item_scheduler`'s "skip a job with a pending approval" reads `has_pending_run_proposal`.
- Tests: an expired card is 409 and its run closed; Command Center's pending list returns run proposals; a job with a pending card is skipped by the scheduler.

### Task 4: The agent chat answers its run's card

- Remove the "Cannot send messages while an action is awaiting approval" guard.
- `prepare_turn` in an agent chat: a typed answer to a pending run card resolves it (apply resumes the run in the background) and the turn is **answer-only**: the user message is saved, no agent call; the batch response and the stream's `done` carry `answered_proposals` and no reply. Any other message is a normal turn; the run's card stays pending.
- Tests: typed "ano" resumes once with no agent reply (batch and stream); "Not now" in words ends the run; a question runs a normal turn and leaves the card pending; the eval harness skips answer-only turns.

### Task 5: Web - one card everywhere

- The approval message's special card (`render.ts addApprovalRequestMessageToUI`, `parseApprovalRequestMessage`) is replaced by the proposal card on that message; old messages keep rendering (their migrated proposal links to them).
- Command Center's approval cards render `renderProposalCard` (with the job's name above it) and answer through the proposal endpoints; `api/jobs.ts` approval calls go.
- The composer's approval lock (`setInputBlockedForApproval`) goes. An answer-only turn shows the user's message delivered and the card resolved; the run's report arrives through the agent conversation sync.
- Tests: unit for the Command Center card and the answer-only turn; E2E (desktop + mobile): approve a run card in the agent chat and in Command Center, type "ano" in the agent chat.

### Task 6: Docs, What's new, instrumentation, gate, review, deploy

- `docs/features/proposals.md` (run origin, gates, answer-only turns), `docs/features/agents.md` (approvals section), regular-review: run cards per kind and how long runs wait; TODO: drop `job_approvals` after one release, re-measure.
- What's new (cs + en): agents ask with the same card; you can reply in their chat while they wait.
- Full gate, Opus whole-branch review, one fix pass, deploy, CI watch.
