# Client reliability and speed - design

Nov 16 2026. Small project, approved ("SGTM"). From the Nov 15 2026 audit (TODO
"Client findings").

## Why

1. **Failed sends are not resent on reconnect.** The offline toast promises
   "Messages you send will be kept and retried", but `handleOnline`
   (`web/src/core/connectivity.ts`) only swaps the toast; a failed bubble waits
   for a manual Retry. Phones drop the connection in the background often.
2. **Streaming redraws the whole reply per token** - marked + DOMPurify +
   innerHTML + live code highlighting on every `token` event, KaTeX uncached.
   Long replies on a phone redraw hundreds of times a second.
3. **Startup is unmeasured.** The user is "not very annoyed by slow opening,
   but we might want to measure it": measure before deciding on a cached
   sidebar or lazy KaTeX (519 KB in the entry bundle).

Non-goals: a cached sidebar, lazy KaTeX, read-aloud, dictation (later, from
data). Anti-goals: a message sent twice; a discarded message coming back; a
resend loop; a visible difference in the final rendered reply.

## Design

### 1. Resend on reconnect

- Triggers: the `online` event, and `visibilitychange` to visible while
  `navigator.onLine`.
- Scope: failed outbox entries of the **open** conversation owned by no other
  live tab, oldest first, one at a time (the next only after the previous
  send settled), and only while the conversation has no active request.
  Other conversations: their failed entries are resent when opened, after
  `reconcileOutboxWithServer` (it drops entries the server already has).
- At most one automatic resend per entry per trigger; a resend that fails
  again stays failed with Retry/Discard. Discarded entries are gone from the
  outbox, so they cannot come back.
- Safe against duplicates: the server rejects a repeated `client_message_id`
  with 409, which the client reads as "already landed".
- Through the existing path (`restoreOutboxEntry` + `dispatchSend`, as
  `retryFailedMessage` does). A "Resent N message(s)" info toast only when
  something was resent. Log `Outbox resend` (count, trigger) via the client
  logger.

### 2. One redraw per frame

- `handleToken` keeps accumulating `state.fullContent` and snapshots to the
  store per token; the DOM update (`updateStreamingMessage`) is scheduled
  with `requestAnimationFrame`, coalesced (one pending frame per message,
  latest content wins). Anything that finalizes or replaces the message
  (done, error, recovery, conversation switch) flushes or cancels the pending
  frame first, so the final render is exactly today's.
- KaTeX: a bounded cache (Map, ~500 entries, LRU-ish by insertion) keyed by
  `displayMode + tex` in `web/src/utils/markdown.ts`.

### 3. Startup timing

- Marks with `performance.now()` at: script start (main.ts), auth settled,
  initial data stored, initial route opened, app ready (`markAppReady`,
  signed-in path only). Plus navigation timing (`responseEnd`,
  `domContentLoaded`) from `performance.getEntriesByType('navigation')`.
- One `POST /api/client-timing` per page load after ready (fire and forget,
  `keepalive`), body: the marks (ms, integers), `standalone` (display-mode
  standalone), `viewport` (mobile < 768 px / desktop), `connection`
  (`navigator.connection.effectiveType` or null), `build` (the build id the
  client errors carry), `route` (the initial route type).
- Stored in a new `client_boot_timings` table (migration; user_id, created_at
  and the fields), purged after 90 days by the scheduler's existing purge.
  Not the journal: production keeps ~2 days of it.
- `docs/regular-review.md`: median and p90 `ready_ms` by `standalone` x
  `viewport`. TODO: "Decide on startup speed (~Nov 30 2026)" - lazy KaTeX,
  cached sidebar, or nothing.

## Approaches considered

- Resend: every conversation's failed entries in the background (rejected:
  the send pipeline renders into the open chat) vs the open one plus on open
  (chosen).
- Rendering: a throttle by time (e.g. 50 ms) vs one per animation frame
  (chosen: matches the display, no tuning).
- Timing: log lines (rejected: ~2 days of journal) vs a table (chosen).

## Left to the builder

Exact mark names, the purge hook, the toast copy.

## Verification

Unit/component tests (vitest) for the resend triggers and scope, the frame
coalescing and flush, the KaTeX cache, the timing payload; backend tests for
the endpoint (auth, validation, insert) and purge; an E2E: go offline, send,
come back online, the message is delivered once. Desktop and mobile. Built and
E2E-tested in a worktree (`make build` replaces static/assets for everyone).
