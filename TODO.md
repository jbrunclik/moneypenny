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
- [ ] **Health/recovery coach program** - Third program type on Garmin data. Q2 dedup done - shared program factory is in place.

## Security

- [ ] **Server-side OAuth state validation (S7)** - High. `routes/todoist.py:50`, `routes/calendar.py`: server never validates `state` on callback. Store server-side (kv_store + TTL), validate + invalidate.
- [ ] **Drop Todoist `data:delete` scope (S9)** - High. `todoist_auth.py:39`; prompt-injected page could delete tasks. Reduce to read/write.
- [ ] **Encrypt OAuth/Garmin tokens at rest (S3)** - Tokens are plaintext in SQLite (`models/user.py`). Fernet keyed from env.

## AI-Agent Best Practices

- [ ] **Agent-behavior evals + observability (A3)** - Eval harness (golden tasks) + per-turn metrics for tool success/tokens/latency/retries.

## Performance / Cost

- [ ] **Compaction summarization off the request path** - `build_compacted_history` calls the summarizer synchronously; bound with timeout and/or precompute in background.

## Reliability

- [ ] **Align prod Python with `requires-python`** - pyproject says >=3.14, prod runs 3.13.

## Code Quality

- [ ] **File-size convention violations (Q3)** - 9+ files 2-3× over the 500-line max; split `chat_streaming.py` and `client.ts` first (highest churn).

## Tests & Tooling

- [ ] **Replace `waitForTimeout` in E2E suite (T1)** - ~245 calls. Triage finding (Jun 11): many are SEMANTIC time waits (debounce windows, assert-nothing-changes-over-a-period, visibility-duration guards) and must stay; the flaky subset is "fixed wait for async data, then assert presence" - replace those with `toContainText`/`toBeVisible` waits (planner mobile dashboard done as the template). Do NOT mass-replace.
- [ ] **Unit tests for agent tools (T2)** - 13 tool modules have zero unit tests; also missing integration tests for `routes/{files,kv_store,memory,system,todoist}.py`.
- [ ] **Tighten lint/coverage gates (T3)** - coverage `fail_under`; ruff `S` rules; `npm audit` level high; per-module mypy overrides.

