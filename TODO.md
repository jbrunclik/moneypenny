# AI Chatbot - TODO

Actionable work only. Tags (S/A/C/X/F/Q/T = June 2026 audit rounds 1-2, R = round 3) kept for traceability. Completed work lives in git history.

## Features

- [ ] **Gmail integration** - Read-only inbox triage via OAuth (reuse the Calendar OAuth pattern): summarize what needs a reply, surface invoices, feed briefings/agents.
- [ ] **Web Push notifications, Phase 3** - Phases 1-2 shipped (Jun 2026: VAPID + subscriptions + Settings toggle; senders: agent finished, approval needed, turn-finished-while-backgrounded; SW suppresses when a focused window is on the target route; see [docs/features/push-notifications.md](docs/features/push-notifications.md)). Remaining:
  - Daily Briefing delivery (depends on the briefing feature below)
  - Planner event reminders (needs a small scheduler loop), program nudges (opt-in per program), budget alerts (threshold check in the cost-recording path)
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

## Planner Dashboard

- [ ] **Two-column layout** - Events left, tasks right; task completion via Todoist API; open-in-Calendar links.
- [ ] **Summary + timeline** - AI daily summary strip, hour-marker timeline, quick-add task.
- [ ] **AI time-blocking** - One-click "schedule my P1/P2 tasks into today's free slots" composing Todoist + Calendar tools.

## Programs (Sports / Language / future)

- [ ] **Spaced repetition for language learning** - SRS review queue over weak vocabulary (kv_store) reusing quiz blocks; daily review nudge via agent.
- [ ] **Health/recovery coach program** - Third program type on Garmin data. Q2 dedup done - shared program factory is in place.

## Security

- [ ] **Drop Todoist `data:delete` scope (S9)** - High. `todoist_auth.py:39`; prompt-injected page could delete tasks. Reduce to read/write.
- [ ] **Encrypt OAuth/Garmin tokens at rest (S3)** - Tokens are plaintext in SQLite (`models/user.py`). Fernet keyed from env.

## AI-Agent Best Practices

- [ ] **Agent-behavior evals + observability (A3)** - Eval harness (golden tasks) + per-turn metrics for tool success/tokens/latency/retries.

## Performance / Cost


## Reliability

- [ ] **Align prod Python with `requires-python`** - pyproject says >=3.14, prod runs 3.13.

## Code Quality

- [ ] **File-size convention violations (Q3, remainder)** - First pass done (chat_streaming.py -> 4 modules; client.ts -> http/sse/client). Remaining over-cap: chat_streaming.py (1147, producer/consumer engine split next), client.ts (1017, domain-module split touches every importer), messaging.ts (1639), prompts.py/schemas.py (declarative), agent.py, models/agent.py, SettingsPopup.ts, routes/agents.py, planner_data.py, todoist.py, thumbnails.ts.

## Tests & Tooling

- [ ] **Webkit search-spec flake under full-suite load** - 2 occurrences (Jun 2026): `search.spec.ts` "navigates to conversation" / "keeps search results visible" fail with search results never rendering ("Type to search conversations" prompt despite filled input) + the known stray version banner (see `error-ui.visual.ts:11` workaround). Not reproducible isolated: 0/240 webkit repeat-runs on both clean and modified trees; only fails with all projects running in parallel. Suspect load-dependent race between SearchInput debounce and sidebar/store updates. Next step: capture a trace with `--trace=on` during a full-suite run, or instrument store.searchQuery transitions.


