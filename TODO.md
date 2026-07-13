# AI Chatbot - TODO

Actionable work only. Tags (S/A/C/X/F/Q/T = June 2026 audit rounds 1-2, R = round 3) kept for traceability. Completed work lives in git history.

## Features

- [ ] **Gmail integration** - Read-only inbox triage via OAuth (reuse the Calendar OAuth pattern): summarize what needs a reply, surface invoices, feed briefings/agents.
- [ ] **Web Push notifications, Phase 3** - Phases 1-2 + Daily Briefing shipped (Jun 2026; see [docs/features/push-notifications.md](docs/features/push-notifications.md)). Remaining:
  - Planner event reminders (needs a small scheduler loop), program nudges (opt-in per program), budget alerts (threshold check in the cost-recording path)
  - Cross-device read-state suppression if stale notifications annoy: grace-delay sends ~30-60s and skip when the message was viewed anywhere (agents have last_viewed_at; regular conversations would need a viewed ping + column)
- [ ] **Daily Briefing follow-ups** - Core shipped (Jun 2026: opt-in toggle + delivery time in Settings, backed by a system-managed agent). Remaining ideas: evening review variant (second time slot), richer default prompt iteration based on real briefings.
- [ ] **Personal knowledge base** - Persistent user documents searchable across conversations. SQLite FTS5 over extracted text is enough.
- [ ] **Thinking mode toggle** - Gemini thinking mode with configurable level, long-press UI like the voice-language selector.
- [ ] **Conversation sharing** - Public links for sharing conversations.
- [ ] **Keyboard shortcuts** for common actions.
- [ ] **Voice conversation mode** - Speech-to-text in, text-to-speech out.
- [ ] **Oura integration** for planner health data.
- [ ] **Tool result caching** - In-memory TTL cache for repeated tool calls within a conversation.

## Autonomous Agents

- [ ] **Multi-step workflows** for agents.

## Planner Dashboard

- [ ] **Two-column layout** - Events left, tasks right; task completion via Todoist API; open-in-Calendar links.
- [ ] **Summary + timeline** - AI daily summary strip, hour-marker timeline, quick-add task.
- [ ] **AI time-blocking** - One-click "schedule my P1/P2 tasks into today's free slots" composing Todoist + Calendar tools.

## Programs (Sports / Language / future)

- [ ] **Daily language review nudge** - SRS itself shipped in the tutor prompt (Jun 2026: due-queue batch quiz, mastery/leech handling); remaining: a scheduled nudge ("5 words due today") via push, ideally a system-managed agent like the Daily Briefing.
- [ ] **Health/recovery coach program** - Third program type on Garmin data. Q2 dedup done - shared program factory is in place.

## AI-Agent Best Practices

- [ ] **Agent-behavior evals + observability (A3)** - Eval harness (golden tasks) + per-turn metrics for tool success/tokens/latency/retries.

## Performance / Cost

(Cost tooling: `scripts/analyze_costs.py`. Context caching, token-based compaction, batched `web_search`, and a per-turn tool-round cap all shipped Jun 2026.)

- [ ] **Model routing / tiering by turn difficulty** - the biggest untapped cost lever, and a real-agent pattern in its own right. Everything currently runs on `gemini-3.5-flash` ($1.50/$9 per M tok); a large share of turns are short and trivial (greetings, quick lookups, one-line follow-ups) yet pay frontier-flash rates. Route by predicted difficulty: cheap/small model for simple turns, the strong model reserved for genuinely hard requests (multi-step reasoning, tool orchestration, code). Two viable shapes: (a) a lightweight up-front classifier — reuse the `should_plan` pattern in `graph.py`, which already does a fast Flash classification, to also emit a model tier; or (b) escalation — start on the cheap model and bump to the strong one when the turn needs tools / the classifier flags complexity / a retry is needed. Caveats to design around: the context cache is keyed per `(profile, model)` (`context_cache.py`), so mixing models fragments cache hits — weigh cheaper tokens vs lost cache; and the cheap model must hold tool-calling quality (validate against the agent graph, not just chat). Add a `MODELS`/pricing tier table in `config.py` and measure the blended cost/msg via `scripts/analyze_costs.py` (already groups BY MODEL) before/after.

## Reliability

- [ ] **Align prod Python with `requires-python`** - pyproject says >=3.14, prod runs 3.13.

## Code Quality

- [ ] **File-size convention violations (Q3, remainder)** - First pass done (chat_streaming.py -> 4 modules; client.ts -> http/sse/client). Remaining over-cap: chat_streaming.py (1147, producer/consumer engine split next), client.ts (1017, domain-module split touches every importer), messaging.ts (1639), prompts.py/schemas.py (declarative), agent.py, models/agent.py, SettingsPopup.ts, routes/agents.py, planner_data.py, todoist.py, thumbnails.ts.

## Tests & Tooling

- [ ] **Re-upgrade TypeScript to 7.x** - Pinned back to ^6.0.3 (Jul 2026) because `typescript-eslint@8.63.0` caps its peer range at `<6.1.0`, which broke `npm ci` in the dependency-audit workflow after Dependabot merged the TS 7.0.2 bump (#182). Dependabot now ignores `typescript >=7.0.0` in [.github/dependabot.yml](.github/dependabot.yml). When typescript-eslint ships TS 7 support: bump both together, remove the ignore rule, and verify `npm ci` + typecheck + lint pass.

- [ ] **Webkit search-spec flake under full-suite load** - 2 occurrences (Jun 2026), still unexplained after a deep hunt (Jun 12):
  - The "stray version banner" clue was a red herring: `.version-banner` hides via `transform: translateY(-100%)` so it is ALWAYS in the accessibility tree and appears in every failure snapshot.
  - Real failure state: `isSearchActive=true` + `store.searchQuery=''` + empty input after `fill()`. Only in-app paths producing that are Escape-on-input or the clear button - neither happens in the specs.
  - Not reproducible: ~430 additional executions (288 webkit repeats under a parallel heavy-spec load generator + 2 more full-suite runs with `--trace=retain-on-failure`) all passed.
  - Forensics now in place: `SearchResults.ts` logs a warning when the hint renders while the DOM input has text (distinguishes lost-input-event vs cleared-input); CI retries record traces incl. console, so the next natural occurrence is diagnosable.
  - Local-env hazard found en route (likely unrelated but nasty): a leaked/manual server on 8001 + `reuseExistingServer` + a rebuild = the old in-memory Vite manifest points at deleted hashed assets -> mass spec failures. If a weird local E2E failure wave appears, check `lsof -iTCP:8001` first.


