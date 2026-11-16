# Client Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Failed sends resend on reconnect, streaming redraws at most once per frame, and startup reports its timing.

**Architecture:** A small `outbox-resend.ts` in `web/src/core/` resends the open chat's failed entries on `online`/visible and after a conversation load. `handleToken` schedules `updateStreamingMessage` through a per-message rAF coalescer that every finalize path flushes. Startup marks go to `POST /api/client-timing` and a `client_boot_timings` table.

**Tech Stack:** TypeScript (vitest, Playwright), Flask/APIFlask, SQLite (yoyo).

**Spec:** docs/superpowers/specs/2026-11-16-client-reliability-design.md

## Global Constraints

- Work in a git worktree under `.claude/worktrees/client-reliability` on branch `client-reliability`; fast-forward main at the end (`make build` and E2E must not touch the shared checkout).
- Migration `0096_client_boot_timings` (check the highest number on main right before committing).
- Constants in `web/src/config.ts` with units: `KATEX_CACHE_MAX_ENTRIES = 500`; backend `CLIENT_BOOT_TIMINGS_RETENTION_DAYS = 90`.
- New endpoint: schema in `src/api/schemas/`, route, `make openapi`, `make types`, E2E mock server intercept if the app calls it under E2E.
- Gate: `make lint` + `make test-all` (E2E on `E2E_PORT=8012`); desktop and mobile; TDD.

## Review Focus

- A failed entry whose original POST did land: the resend gets 409 and the bubble ends as sent, not failed (Task 1 test).
- Two tabs: an entry owned by another live tab is not resent (Task 1 test).
- A stream that ends (done/error/stop) between a token and its frame shows the final content, never a stale frame after it (Task 2 test).
- A switch to another conversation with a frame pending draws nothing into the new conversation (Task 2 test).
- A client-timing POST with absurd values (negative, > 10 min, unknown keys) is rejected 400, never stored (Task 3 test).

---

### Task 1: Resend failed sends on reconnect

**Files:** Create `web/src/core/outbox-resend.ts`; Modify `web/src/core/connectivity.ts`, `web/src/core/outbox.ts` (a `failedEntries(convId)` reader), the conversation-load site that calls `reconcileOutboxWithServer` (`web/src/core/conversation.ts`); Test `web/tests/unit/outbox-resend.test.ts`, `web/tests/e2e/outbox-resend.spec.ts`

**Interfaces:** Produces `resendFailedSends(trigger: 'online' | 'visible' | 'open'): Promise<number>` (count resent) and `initOutboxResend(): void`.

- [ ] Step 1: unit tests - `online` with two failed entries in the open chat dispatches them oldest first, the second only after the first settled; an entry owned by another live tab and one in another conversation are skipped; nothing while the chat has an active request; a second trigger during a running resend does not start a parallel one; `visible` while offline does nothing; a "Resent 2 messages" info toast only when count > 0; opening a conversation with a failed entry resends it after reconcile. E2E: offline (`context.setOffline(true)`), send, online -> one user message on the server, no "Not sent" bubble.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement; reuse `restoreOutboxEntry` + `resetAutoRetry` + `dispatchSend` (move the shared part of `retryFailedMessage` into one exported helper rather than duplicating it).
- [ ] Step 4: tests pass; commit `fix(chat): failed sends are resent when the connection returns`.

### Task 2: One redraw per frame, cached KaTeX

**Files:** Modify `web/src/core/stream-events.ts` (`handleToken`), `web/src/components/messages/streaming.ts` (a `scheduleStreamingUpdate` / `flushStreamingUpdate` pair), the finalize paths (`stream-done.ts`, `stream-recovery.ts`, the error/stop handlers), `web/src/utils/markdown.ts` (KaTeX cache), `web/src/config.ts`; Test `web/tests/unit/streaming-frames.test.ts`, `web/tests/unit/markdown-katex-cache.test.ts`

- [ ] Step 1: tests - 50 tokens within one frame render once with the full text; a done event before the frame shows the final content and no later frame overwrites it; a conversation switch cancels the pending frame; `renderMarkdown` of the same formula twice calls `katex.renderToString` once; the cache never exceeds `KATEX_CACHE_MAX_ENTRIES`; display and inline of one tex are cached apart.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: tests pass; commit `perf(chat): streaming redraws once per frame, KaTeX cached`.

### Task 3: Startup timing

**Files:** Create `migrations/0096_client_boot_timings.py`, `src/db/models/client_boot_timings.py`, `src/api/schemas/client_timing.py`, `src/api/routes/client_timing.py`, `web/src/core/startup/boot-timing.ts`; Modify route registration, `src/agent/scheduler.py` (purge), `src/config.py`, the startup files that mark stages, `static/openapi.json`, generated types, `docs/regular-review.md`, `docs/features/` (a short section where client errors are documented), TODO; Test `tests/integration/test_routes_client_timing.py`, `web/tests/unit/boot-timing.test.ts`

**Interfaces:** `POST /api/client-timing` body `{marks: {script_ms, auth_ms, data_ms, route_ms, ready_ms, response_end_ms, dom_content_loaded_ms}: int|null each (0..600000), standalone: bool, viewport: "mobile"|"desktop", connection: str|null (<=16), build: str|null (<=32), route: str (<=24)}` -> 204; `Database.add_client_boot_timing(user_id, payload)`, `purge_client_boot_timings(older_than_days) -> int`.

- [ ] Step 1: tests - the endpoint stores one row (auth required, 401 without); negative, > 600000, unknown keys, a long build -> 400 and no row; the purge deletes rows older than 90 days only; the client posts once per load after ready with integer marks, `standalone` from `matchMedia('(display-mode: standalone)')`, `viewport` from width < 768, `keepalive: true`, never when signed out, and a failing POST is swallowed.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement; `make openapi`, `make types`; the E2E mock server answers the endpoint 204 if E2E traffic reaches it.
- [ ] Step 4: tests pass; docs and TODO ("Decide on startup speed (~Nov 30 2026)", remove the shipped Client-findings lines: failed sends, streaming re-render; the Cold start line becomes the decision line); commit `feat(client): startup reports its timing`.

### Finish

- [ ] `make lint`, `E2E_PORT=8012 make test-all` in the worktree; desktop + mobile check of a streamed reply and an offline resend; final review; fast-forward main, push, deploy, health check.
