# Moneypenny Documentation

This directory contains detailed documentation for the Moneypenny project, organized by feature area and concern.

## Documentation Structure

### Features (`features/`)
Feature-specific documentation covering user-facing functionality:

- **[admin.md](features/admin.md)** - Admin page (ADMIN_EMAILS: spend, agent health, web-search quotas, response quality, browser errors, system facts, device check runs), browser error reporting, the in-app device check runner, and the daily spend warning banner
- **[agents.md](features/agents.md)** - Autonomous agents: schema, cron scheduling, execution flow, approval workflow, budgets, Command Center UI, agent-to-agent communication, routing race prevention
- **[agent-tools.md](features/agent-tools.md)** - Tool binding and permissions (always-bound vs `ALWAYS_SAFE_TOOLS`, three layers), search provider chain, tool security, adding a new tool, K/V store, browser tool (action batches, page state), skills (`load_skill`, adding a skill), grounding directive on web results
- **[freshness.md](features/freshness.md)** - Current facts: freshness gate (lookup before the turn, dated queries, failed-lookup note), `published` dates and the `_recency` note on search results, snippets-are-not-verification directive, recent-news grounding scope, config, evals
- **[grounding.md](features/grounding.md)** - Post-answer grounding check: numbered turn pages, two-list verifier, claim validation, annotations storage and API, `MSG_CONTEXT` entry, claim card / claims sheet / footer UI
- **[deep-research.md](features/deep-research.md)** - Deep research overview and what the user sees: `propose_deep_research` offer card, Start / No thanks, autostart, rounds, progress panel and report summary
- **[deep-research-pipeline.md](features/deep-research-pipeline.md)** - Deep research pipeline: start, briefs, parallel subagents with a shared board, merge, Pro report, grounding check, follow-ups; deadlines, Finish now / Stop, concurrency
- **[deep-research-data.md](features/deep-research-data.md)** - Deep research storage and events: `messages.research`, `research_*` SSE events, `messages.action` and action rows
- **[deep-research-ops.md](features/deep-research-ops.md)** - Deep research cost, estimate and push, configuration, telemetry, evals, pitfalls, tests
- **[artifacts.md](features/artifacts.md)** - Inline artifacts: `create_artifact` / `update_artifact` / `read_artifact`, versions and triggers, the sandboxed `/artifact-frame` and its CSP, the `mp` bridge, the `--mp-*` design system, per-device sizing, `artifact` SSE event, evals
- **[chat-and-streaming.md](features/chat-and-streaming.md)** - Chat turn lifecycle (shared turn setup, streaming producer/consumer/finalize), stop, placeholder recovery, resumable streams, outbox, frontend send / re-run / retry
- **[thinking-and-sources.md](features/thinking-and-sources.md)** - Thinking indicator and tool trace, retry status line, automatic source chips
- **[file-handling.md](features/file-handling.md)** - `retrieve_file`, clipboard paste, client-side image compression, upload progress, background thumbnails, copy to clipboard, video uploads and file retention
- **[image-generation.md](features/image-generation.md)** - `generate_image`: aspect ratios, resolution, image-to-image editing, history image references
- **[code-execution.md](features/code-execution.md)** - `execute_code` Docker sandbox: custom image, security limits, per-conversation sessions, output files
- **[voice-and-tts.md](features/voice-and-tts.md)** - Voice input (speech-to-text), text-to-speech
- **[search.md](features/search.md)** - Full-text search with SQLite FTS5, O(1) message navigation
- **[sync.md](features/sync.md)** - Real-time synchronization across devices/tabs with timestamp-based polling
- **[integrations.md](features/integrations.md)** - Integrations hub: which tools bind when, and the shared "not connected" / "disconnected" tool results
- **[todoist.md](features/todoist.md)** - Todoist OAuth, `todoist` tool actions, task assignment
- **[google-calendar.md](features/google-calendar.md)** - Google Calendar OAuth, token refresh and error classes, multi-calendar selection, privacy page
- **[planner.md](features/planner.md)** - Planner mode: 7-day dashboard, `refresh_planner_dashboard`, caching, Yr.no weather
- **[garmin.md](features/garmin.md)** - Garmin Connect health data (`garmin_connect`) and workout editing (`garmin_workout`)
- **[whatsapp.md](features/whatsapp.md)** - WhatsApp notifications for autonomous agents (Meta Cloud API templates)
- **[push-notifications.md](features/push-notifications.md)** - Web Push (VAPID) to the user's devices; the primary notification rail for autonomous agents
- **[language-learning.md](features/language-learning.md)** - Language programs: AI tutor, assessments, lessons, quizzes
- **[rouvy.md](features/rouvy.md)** - Rouvy indoor-cycling workout CRUD (headless login + cookie-authed httpx; upload agent-authored ZWO)
- **[location.md](features/location.md)** - Places search and routing (Mapy.com), device location sharing, saved places, location-aware prompt context and briefing
- **[memory-and-context.md](features/memory-and-context.md)** - User memory, custom instructions, user context, anonymous mode, memory defragmentation
- **[cost-tracking.md](features/cost-tracking.md)** - Token usage tracking, image generation costs, currency rates, monthly aggregation
- **[ui-features.md](features/ui-features.md)** - UI features overview, linking the pages below
- **[ui-composer.md](features/ui-composer.md)** - Input toolbar, Enter-to-send, force tools, clipboard paste, program quick actions
- **[ui-messages.md](features/ui-messages.md)** - Message content: link detection and security, image lightbox, copy to clipboard, Mermaid diagrams, inline artifact cards
- **[ui-conversations.md](features/ui-conversations.md)** - Conversation rename, delete, bulk delete and trash
- **[ui-app-shell.md](features/ui-app-shell.md)** - Deep linking, version update banner, color scheme

### Architecture (`architecture/`)
System design and architectural decisions:

- **[authentication.md](architecture/authentication.md)** - Google Sign-In, JWT token handling, token refresh, @require_auth decorator
- **[database.md](architecture/database.md)** - Blob storage, connection pooling, indexes, performance monitoring, vacuum, backup, best practices
- **[api-design.md](architecture/api-design.md)** - OpenAPI documentation and type generation, route organization, request validation (including magic bytes)
- **[rate-limiting.md](architecture/rate-limiting.md)** - Flask-Limiter categories, key strategy, headers, decorators, shared SQLite counter storage (fail open)
- **[error-handling.md](architecture/error-handling.md)** - Standard error format and codes, frontend toasts/modals, API client timeouts, failed chat sends
- **[agent-graph.md](architecture/agent-graph.md)** - LangGraph loop: chat node retries and the `retry` event, tool node, self-correction, mid-run steering, tool round economics, stopped-early replies
- **[conversation-context.md](architecture/conversation-context.md)** - History enrichment (MSG_CONTEXT), tool-output digests, segmented conversation compaction, agent compaction
- **[streaming-metadata.md](architecture/streaming-metadata.md)** - MSG_CONTEXT stripping in the stream, placeholder messages and client-side stream recovery
- **[scheduled-jobs.md](architecture/scheduled-jobs.md)** - Time-scheduled work: systemd timers in production, dev_scheduler loop in development, job inventory, how to add a new job

### UI (`ui/`)
User interface patterns and implementations:

- **[scroll-behavior.md](ui/scroll-behavior.md)** - Complex scroll scenarios, programmatic scroll wrapper, streaming auto-scroll, race condition fixes, cursor-based pagination
- **[mobile-and-pwa.md](ui/mobile-and-pwa.md)** - iOS Safari gotchas (9 documented issues), touch gestures, PWA viewport fixes
- **[components.md](ui/components.md)** - Component structure, event delegation, DOM helpers, popup escape handler, adding components, chat header and compaction indicator
- **[design-system.md](ui/design-system.md)** - CSS file layout and cascade order, design tokens (color, spacing, type, motion, z-index), light/dark themes, glass materials
- **[planner-dashboard.md](ui/planner-dashboard.md)** - Planner dashboard UI: content order, CSS classes, priority rings, mobile layout, scroll-to-top
- **[patterns.md](ui/patterns.md)** - Standard interaction and visual patterns to reuse in new features

### General

- **[setup.md](setup.md)** - Operator setup guides: code-execution sandbox, browser automation, Google Sign In, Todoist, Google Calendar, Garmin Connect, WhatsApp
- **[deployment.md](deployment.md)** - Production operations: systemd maintenance timers (backup, vacuum, currency, memory defrag), nginx reverse-proxy config, log rotation, worker memory profiling (tracemalloc snapshots on SIGUSR2)
- **[testing.md](testing.md)** - Testing index: commands, TDD, isolation and mocking rules, flaky-test prevention, lint/coverage/audit gates
- **[testing/backend.md](testing/backend.md)** - pytest layout, fixtures, chat-path mock return shapes, writing backend tests
- **[testing/frontend.md](testing/frontend.md)** - Vitest unit/component tests, Playwright E2E, the E2E mock server and `/test/*` endpoints, planner tests
- **[testing/e2e-reliability.md](testing/e2e-reliability.md)** - Starved-runner signature, visual flakes as state races, CI first-run reliability pass, E2E gotchas
- **[testing/visual.md](testing/visual.md)** - Visual regression tests: darwin vs Linux baselines, regeneration via Docker or CI
- **[testing/evals.md](testing/evals.md)** - Agent behavior evals: golden cases + LLM judge (`make eval`), when to run, case authoring
- **[logging.md](logging.md)** - Structured logging (backend JSON format, frontend logger utility), request IDs, logging guidelines
- **[regular-review.md](regular-review.md)** - The weekly/monthly review checklist (`/product-review`): errors users hit (browser and server), agents, cost and speed, answer quality, code-health baselines, dependencies and parked TODO triggers; report template
- **[conventions.md](conventions.md)** - Engineering standards: every rule with its ID and enforcer (security, layers, errors, logging, typing, size, testing, agent workflow)
- **[superpowers/specs/](superpowers/specs/)** - Design specs still referenced by open work (parked or with deferred follow-ups). Shipped specs and plans are deleted; git history keeps them

## Quick Links

### Most Referenced

- [Agents](features/agents.md) - Autonomous agents and Command Center
- [Chat and Streaming](features/chat-and-streaming.md) - Core chat functionality
- [File Handling](features/file-handling.md) - Working with files and images
- [Database](architecture/database.md) - Database architecture and best practices
- [API Design](architecture/api-design.md) - API patterns and validation
- [Agent Graph](architecture/agent-graph.md) - The agent loop behind every turn
- [Testing](testing.md) - How to write and run tests

### For New Developers

Start here to understand the system:
1. Read [../AGENTS.md](../AGENTS.md) (= CLAUDE.md) for commands and hard rules
2. Explore [Architecture](architecture/) docs to understand system design
3. Review [Features](features/) docs for specific functionality
4. Check [Testing](testing.md) before making changes

### For Feature Development

When working on a specific area:
1. Read the relevant feature doc first
2. Check related architecture docs for design patterns
3. Review testing patterns and add tests
4. Follow [conventions.md](conventions.md)

### For Debugging

Common debugging scenarios:
- **Scroll issues**: See [Scroll Behavior](ui/scroll-behavior.md) - 25+ documented scenarios
- **Mobile/PWA issues**: See [Mobile and PWA](ui/mobile-and-pwa.md) - iOS Safari gotchas
- **Authentication errors**: See [Authentication](architecture/authentication.md) - Error codes and handling
- **Database performance**: See [Database](architecture/database.md) - Slow query logging, indexes
- **API errors**: See [Error Handling](architecture/error-handling.md) - Error format and frontend handling
- **Agent loops, retries, round cap**: See [Agent Graph](architecture/agent-graph.md)
- **Stream dropped / reply missing after reload**: See [Streaming](architecture/streaming-metadata.md) and the resume section of [Chat and Streaming](features/chat-and-streaming.md)

## Documentation Guidelines

- **Where things go**: a feature's behavior, configuration and endpoints in
  its `features/` page; system design in `architecture/`; UI patterns in
  `ui/`; test practice in `testing/`; rules in [conventions.md](conventions.md).
  AGENTS.md gets a pointer only for a new everyday command or hard rule.
- **Update in the same commit** as the code change; a new pattern or pitfall
  is worth a line where the next agent will look for it.
- **One home per fact**: link instead of restating, so nothing drifts.
- **Numbers carry a date** ("78 cases, Oct 2026"), or they read as current
  forever.
- **Keep pages under ~500 lines** - split by subsystem. A new page goes into
  this index; `tests/unit/test_docs_links.py` checks links.
- **Plans and specs** from `/new-feature` live in `superpowers/` while the work
  is open and are deleted once it ships (git history keeps them).
