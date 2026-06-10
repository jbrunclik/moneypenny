# AI Chatbot - TODO

Actionable work only. Tags (S/A/C/X/F/Q/T = June 2026 audit rounds 1-2, R = round 3) kept for traceability. Completed work lives in git history.

## Features

- [ ] **Gmail integration** - Read-only inbox triage via OAuth (reuse the Calendar OAuth pattern): summarize what needs a reply, surface invoices, feed briefings/agents.
- [ ] **Web Push notifications** - Primary notification rail for agent results, approval nudges, briefings, unread messages. Replaces WhatsApp friction; keep WhatsApp as fallback.
- [ ] **Daily Briefing (first-class)** - Morning briefing: planner data + Garmin readiness + AI recommendations, via push on a schedule. Evening review variant. Depends on: Web Push.
- [ ] **Personal knowledge base** - Persistent user documents searchable across conversations. SQLite FTS5 over extracted text is enough.
- [ ] **Thinking mode toggle** - Gemini thinking mode with configurable level, long-press UI like the voice-language selector.
- [ ] **Conversation sharing** - Public links for sharing conversations.
- [ ] **Keyboard shortcuts** for common actions.
- [ ] **Voice conversation mode** - Speech-to-text in, text-to-speech out.
- [ ] **Oura integration** for planner health data.
- [ ] **Tool result caching** - In-memory TTL cache for repeated tool calls within a conversation.

## Autonomous Agents

- [ ] **Multi-step workflows** for agents.
- [ ] **User-facing agent observability** - "What did my agents do this week and what did it cost" view in Command Center.
- [ ] **Bound agent-trigger depth (S5)** - Low. Cycles are blocked; add `MAX_TRIGGER_DEPTH` for distinct-agent chains.

## Planner Dashboard

- [ ] **Two-column layout** - Events left, tasks right; task completion via Todoist API; open-in-Calendar links.
- [ ] **Summary + timeline** - AI daily summary strip, hour-marker timeline, quick-add task.
- [ ] **AI time-blocking** - One-click "schedule my P1/P2 tasks into today's free slots" composing Todoist + Calendar tools.

## Programs (Sports / Language / future)

- [ ] **Spaced repetition for language learning** - SRS review queue over weak vocabulary (kv_store) reusing quiz blocks; daily review nudge via agent.
- [ ] **Health/recovery coach program** - Third program type on Garmin data. Prerequisite: Q2 dedup below.

## Security

- [ ] **Server-side OAuth state validation (S7)** - High. `routes/todoist.py:50`, `routes/calendar.py`: server never validates `state` on callback. Store server-side (kv_store + TTL), validate + invalidate.
- [ ] **Remove `--no-sandbox` from agent browser (S8)** - High. `browser.py:83` disables Chromium OS sandboxing while browsing untrusted pages.
- [ ] **Drop Todoist `data:delete` scope (S9)** - High. `todoist_auth.py:39`; prompt-injected page could delete tasks. Reduce to read/write.
- [ ] **Encrypt OAuth/Garmin tokens at rest (S3)** - Tokens are plaintext in SQLite (`models/user.py`). Fernet keyed from env.
- [ ] **Security headers + CORS (S10)** - `app.py` sets no X-Frame-Options/CSP/HSTS. Add `@app.after_request`.
- [ ] **Magic-byte upload validation (S11)** - `schemas.py` trusts declared MIME; sniff with `python-magic`.
- [ ] **Verify code-sandbox network isolation (S4)** - Pass network-disabled explicitly; regression-test that sockets fail inside the sandbox.
- [ ] **Rate limiting: proxy-aware client IP** - `ProxyFix` + X-Forwarded-For limiter key. `app.py`, `rate_limiting.py`.
- [ ] **Logout: clear all sensitive state** - `store.logout()` leaves messages/pagination/activeRequests in memory. Add `resetStore()`.
- [ ] **Harden `blob_store.delete_by_prefixes` SQL (S6)** - Low. f-string WHERE (bound params, fragile). Parameterized deletes.

## AI-Agent Best Practices

- [ ] **Tool error `retriable` flag (A1 remainder)** - Add `retriable` to the `{"error": ...}` envelope so self-correction skips pointless retries (e.g. "integration not configured").
- [ ] **Bound long-term memory (A2)** - `validate_memory_operations` (`api/utils.py`) checks presence not size; cap per-entry + total, reject oversized writes.
- [ ] **Agent-behavior evals + observability (A3)** - Eval harness (golden tasks) + per-turn metrics for tool success/tokens/latency/retries.

## Performance / Cost

- [ ] **Right-size the planning classifier (C1 follow-up)** - From `planning_classifier` telemetry, decide: gate tighter, fold into main call, or disable by default. `graph.py::should_plan`.
- [ ] **Compaction summarization off the request path** - `build_compacted_history` calls the summarizer synchronously; bound with timeout and/or precompute in background.
- [ ] **Context-cache hit-rate telemetry (C2)** - Log hit/create/adopt rates per profile in `context_cache.py`; assert cached tool set matches active set.
- [ ] **N+1 queries in agent listing (Q1)** - `routes/agents.py:139-145` runs 3 queries per agent; batch by agent_id.
- [ ] **Cache program prompts (sports/language)** - These profiles are fully uncached: ~6K tokens of static prompt re-billed every turn. Split static program instructions (cacheable) from the per-turn KV data (dynamic tail), like the standard profile.

## Reliability

- [ ] **Browser worker recovery after stuck Playwright op (R1)** - `browser.py:110`: timed-out worker stays blocked forever; add unhealthy flag + restart. Clamp `timeout_ms=0` (= infinite in Playwright).
- [ ] **OAuth refresh race loses rotated refresh tokens (R2)** - `google_calendar.py:29`, `routes/calendar.py:69` (+ Todoist): unlocked read-refresh-write. Per-user lock or compare-and-swap.
- [ ] **Approval + sibling tools orphans tool calls (R3)** - `request_approval` mid-batch aborts `executor.map`; siblings get no ToolMessage → Gemini rejects next turn. Pre-split like `_split_blocked_tool_calls`.
- [ ] **Blob deletion ordering (R4)** - 5 delete paths remove blobs BEFORE committing row deletion; crash leaves rows pointing at deleted blobs. Commit rows first.
- [ ] **Thumbnail TOCTOU on messages.files (R5)** - `message.py:636` read-modify-writes whole JSON; concurrent workers lose updates. `BEGIN IMMEDIATE` or `json_set`.
- [ ] **Temp file leak in sandbox extraction (R7)** - `code_execution.py:178`: unlink only on happy path; move to `finally`.
- [ ] **WhatsApp agent_name not template-sanitized (R8)** - `whatsapp.py:319`: raw agent name in template param; Meta rejects newlines/multi-spaces.
- [ ] **Migration hygiene (R10)** - 0025-0028, 0033 lack `__depends__`; 0025's rollback is a silently-succeeding comment.
- [ ] **Harden streaming save on crash (X1)** - Distinguish placeholder deleted-vs-failed; persist partial content on arbitrary crash/`BaseException` (deadline path already saves). Observed in prod Jun 2026.
- [ ] **Remaining lazy-init races under gthread** - Low. browser `_worker`/`_browser_available`, `_docker_available`, cleanup-thread guards. Double-checked locking when convenient.
- [ ] **Align prod Python with `requires-python`** - pyproject says >=3.14, prod runs 3.13.
- [ ] **SyncManager.start() error handling** - Unhandled rejection silently disables sync. `init.ts`, `SyncManager.ts`.

## Code Quality

- [ ] **Deduplicate sports/language program modules (Q2)** - Near-identical CRUD; extract shared program-routes factory before a third program lands.
- [ ] **File-size convention violations (Q3)** - 9+ files 2-3× over the 500-line max; split `chat_streaming.py` and `client.ts` first (highest churn).
- [ ] **Refactor `save_message_to_db` (X2)** - ~214 lines mixing save/title/metadata/cost. Extract sub-steps. (Overlaps Q3.)
- [ ] **Tidy exception swallowing (X3)** - Silent `except: pass` in `connection_pool.py`, `browser.py` (4×), `chat_streaming.py:137`, `planner_data.py:25`. Log at DEBUG.
- [ ] **Consolidate four scroll listeners on `#messages`** into one scroll manager.

## Frontend

- [ ] **Catch-path recovery never sets messageSuccessful (R11)** - High, one-liner. `messaging.ts:1010`: spurious "New messages" banner after every mobile recovery.
- [ ] **`timeout` SSE event unhandled by client (R12)** - Add `case 'timeout'` in `processStreamEvent`.
- [ ] **Recovery races a resuming stream reader (R13)** - Recovery should abort the original AbortController before finalizing; late tokens currently overwrite recovered content.
- [ ] **No pagehide/pageshow handlers for iOS bfcache (R14)** - Register `pagehide(persisted)` → mark, `pageshow(persisted)` → attempt recovery.
- [ ] **Recovered message keeps error styling / detached element (R15)** - Guard `isConnected`; remove `message-incomplete` on success.
- [ ] **Stream death before `user_message_saved` unrecoverable (R16)** - Send placeholder id in a response header. (Superseded by resumable streams if that lands.)
- [ ] **Sanitize rendered LLM output — XSS (F1)** - High. LLM/API strings reach `innerHTML` in 7+ places; run rendered markdown through DOMPurify.
- [ ] **VoiceInput listener leak (F2)** - `VoiceInput.ts:413` adds listeners with no cleanup on re-mount.
- [ ] **Sidebar full re-render (F3)** - `Sidebar.ts:610` rebuilds list via innerHTML on every update; go incremental.

## Tests & Tooling

- [ ] **Replace `waitForTimeout` in E2E suite (T1)** - 60+ calls contradict the zero-flake policy; use `expect(...).toBeVisible()` / `waitForFunction`.
- [ ] **Unit tests for agent tools (T2)** - 13 tool modules have zero unit tests; also missing integration tests for `routes/{files,kv_store,memory,system,todoist}.py`.
- [ ] **Tighten lint/coverage gates (T3)** - coverage `fail_under`; ruff `S` rules; `npm audit` level high; per-module mypy overrides.

## Architecture

- [ ] **Resumable streams (mobile resilience)** - Decouple generation from the HTTP connection, journal stream events per assistant-message-id with seq numbers, resume endpoint replays then continues live; client reconnects with offset on `online`/`pageshow`/error. SQLite-backed journal is enough. Obsoletes parts of R13/R16.
