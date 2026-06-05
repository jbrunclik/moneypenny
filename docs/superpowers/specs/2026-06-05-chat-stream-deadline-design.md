# Chat-stream request deadline — design

**Date:** 2026-06-05
**Status:** Approved (design); pending implementation plan

## Problem

The interactive `POST /api/conversations/<id>/chat/stream` path has **no overall
deadline**. The agent runs in a background producer thread that pushes events
onto a queue; the WSGI generator (the worker thread) drains the queue and streams
SSE to the client until the producer signals completion. Nothing bounds total
duration.

Under the previous **sync** gunicorn worker this was masked: gunicorn's
`--timeout` killed the worker mid-stream (`WORKER TIMEOUT` → `SystemExit`),
which at least freed the worker — at the cost of losing generated content (see
TODO X1). We have since switched to the **gthread** worker class so long
*legitimate* streams complete. But gthread does **not** reap a request thread
that is quietly working or producing output (verified: a silent 8 s stream
survived a 4 s `--timeout`). So the gunicorn timeout no longer bounds chat
duration at all — a genuinely hung tool/LLM call would occupy a thread
indefinitely. An **application-level deadline is now load-bearing.**

`Config.CHAT_TIMEOUT` (default 300 s) exists but is **dead config** — referenced
nowhere outside `config.py`.

## Goals

- Bound the duration of an interactive chat turn at the application layer.
- On deadline, **persist the partial content already generated** (do not lose it)
  and notify the client cleanly.
- Guarantee the **gthread worker thread is freed** even if the agent is wedged
  inside a single non-yielding call.
- Stop the agent (and free the producer thread) promptly in the common case.
- Leave the normal completion and client-disconnect paths unchanged.

## Non-goals

- Forcibly killing a runaway Python thread (not possible cooperatively; bounded
  instead by the consumer backstop freeing the worker thread + `TOOL_TIMEOUT`
  bounding individual tool calls).
- Changing the autonomous-agent execution timeout (`AGENT_EXECUTION_TIMEOUT_MINUTES`),
  which governs the background scheduler, not interactive chat.

## Decisions (confirmed with user)

- **Default deadline:** 600 s / 10 min, configurable via the existing
  `CHAT_TIMEOUT` env var. Generous headroom for long legitimate agent runs
  (many tool calls, image generation); matches the gunicorn `--timeout`.
- **On timeout:** save whatever text streamed so far as the assistant message,
  appended with a `…(response timed out)` marker, and send the client a
  `timeout` SSE event. Directly closes the X1 content-loss gap for the timeout
  case.
- **Mechanism:** defense-in-depth (producer cooperative deadline + consumer
  backstop deadline). See below.

## Architecture

Two enforcement points sharing one `CHAT_TIMEOUT`. Wall-clock measured with
`time.monotonic()`.

### 1. Producer cooperative deadline — primary

In `stream_events` (the background thread iterating `agent.stream_chat_events`):

- Compute `deadline = monotonic() + Config.CHAT_TIMEOUT` at thread start.
- In the `for event in agent.stream_chat_events(...)` loop, after handling each
  event, if `monotonic() > deadline` and no `final` event has been seen, **break**.
- On break: log a warning, put a `{"type": "timeout"}` marker onto the queue,
  then put `None` (completion sentinel). Breaking the `for` loop closes the
  agent generator, cooperatively stopping the agent between steps. A tool call
  in flight is independently bounded by `TOOL_TIMEOUT` (90 s), so worst-case
  overrun is `CHAT_TIMEOUT + TOOL_TIMEOUT`.

This stops compute and frees the producer thread whenever the agent is yielding
events (the common case for a long-but-progressing run).

### 2. Consumer backstop deadline — guarantees worker-thread liveness + save

In `_process_event_queue` (the WSGI generator / gthread worker thread):

- Record `start = monotonic()`.
- Accumulate `token` event text into `context.partial_content` (new field; the
  single source of truth for "what the client received").
- Bound each `queue.get` wait by `min(SSE_KEEPALIVE_INTERVAL, remaining)` where
  `remaining = deadline_with_grace - monotonic()`.
- `deadline_with_grace = start + CHAT_TIMEOUT + SSE_KEEPALIVE_INTERVAL` — the
  one-keepalive grace ensures the producer's own deadline normally fires first;
  the consumer is the backstop for when the producer is wedged in a
  non-yielding call (no events flow, so the producer check never runs).
- On either (a) receiving the `{"type":"timeout"}` marker from the producer, or
  (b) `monotonic() > deadline_with_grace`: populate `final_results` with the
  partial content and break (see "Partial save" below). Emit a `timeout` SSE
  event to the client first.

When the consumer returns, the WSGI response completes and the gthread worker
thread is freed — even if the producer thread is still wedged (that thread is
separately bounded by the existing `cleanup_and_save` join with
`STREAM_CLEANUP_THREAD_TIMEOUT`).

### 3. Partial save — reuse existing machinery

The save path already gates on `final_results["ready"]` and calls
`save_message_to_db(content, result_messages, tools, usage, …)`, whose metadata
extractors tolerate empty `result_messages`/`tools`. To persist partial content
on timeout, the consumer:

- sets `final_results["clean_content"] = context.partial_content + TIMEOUT_MARKER`
- sets `final_results["result_messages"] = []`, `["tool_results"] = []`,
  `["usage_info"] = {}`
- sets `final_results["ready"] = True`

Then the existing `_finalize_stream` (or the `cleanup_and_save` fallback on
client disconnect) saves it under `save_lock` exactly as for a normal response.
No changes to the save/lock/cleanup logic itself.

`TIMEOUT_MARKER` is a constant, e.g. `"\n\n_…(response timed out)_"`. If
`partial_content` is empty (deadline hit before any token), save nothing and
delete the placeholder (existing behavior in `generate()`'s `finally`).

## Data flow (timeout case)

```
producer thread:  agent.stream_chat_events ──token──┐ (deadline crossed)
                                                     ├─► break loop, close agent
                                                     ├─► queue.put({"type":"timeout"})
                                                     └─► queue.put(None)
queue:            token, token, …, {"type":"timeout"}, None
consumer thread:  accumulates partial_content; on "timeout" marker (or its own
                  backstop) → emit SSE {"type":"timeout"} → populate final_results
                  (ready=True, partial content) → break
finalize:         _finalize_stream saves partial message under save_lock
client:           receives streamed tokens, then a timeout event, then done
DB:               assistant message = partial text + "…(response timed out)"
```

## Client contract

- New SSE event `{"type": "timeout"}` (optionally with a human-readable
  `message`). The frontend should render the (already-streamed) partial text and
  surface a non-fatal "response timed out" indication. Frontend wiring is a
  follow-up if not trivial; the persisted message already carries the marker.

## Config / docs

- `Config.CHAT_TIMEOUT`: keep name; change default `300` → `600`; update the
  inline comment to describe it as the interactive chat-turn deadline (not just
  a nominal value).
- `.env.example`: document `CHAT_TIMEOUT` as the enforced chat-turn deadline and
  its relationship to `GUNICORN_TIMEOUT` (the app deadline should be ≤ gunicorn
  timeout so the app aborts gracefully first).

## Error handling / edge cases

- **Approval flow:** `ApprovalRequestedException` ends the turn before the
  deadline normally; the deadline must not interfere with the approval path.
- **Client disconnect before deadline:** unchanged — `mark_disconnected` +
  `cleanup_and_save` already handle it; partial-save just makes `ready` true
  earlier in the timeout case.
- **Normal completion before deadline:** the `final` event arrives, `ready` is
  set, deadline checks are no-ops.
- **Empty partial content:** delete placeholder, save nothing (existing path).
- **Idempotent save:** `save_lock` + `saved` flag already prevent double-save
  between generator and cleanup thread; partial-save uses the same flags.

## Testing

Unit tests with a fake/instrumented agent generator (no real LLM):

1. **Producer stops near deadline:** fake agent yields tokens forever; assert the
   producer breaks within ~`CHAT_TIMEOUT` (use a small injected timeout), emits a
   `timeout` marker + `None`.
2. **Consumer saves partial + emits timeout event:** assert a `timeout` SSE event
   is yielded and `final_results` is populated with the accumulated tokens +
   marker, and `save_message_to_db` is called with that content.
3. **Consumer backstop fires when producer never yields:** fake producer that
   sleeps past the grace deadline without emitting events; assert the consumer
   breaks at `CHAT_TIMEOUT + grace` and frees (returns).
4. **Normal completion unchanged:** agent completes before the deadline; assert
   no `timeout` event, full content saved, existing tests still pass.
5. **Empty partial:** deadline before any token; assert nothing saved /
   placeholder deleted.

Use small `CHAT_TIMEOUT`/`SSE_KEEPALIVE_INTERVAL` values via monkeypatch to keep
tests fast.

## Out of scope / follow-ups

- Frontend rendering polish for the `timeout` event (separate, if needed).
- Broader X1 hardening (persisting partial content on arbitrary
  `BaseException`/crash, not just the deadline) remains a separate TODO item;
  this design covers the deadline case.
