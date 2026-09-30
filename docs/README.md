# Moneypenny Documentation

This directory contains detailed documentation for the Moneypenny project, organized by feature area and concern.

## Documentation Structure

### Features (`features/`)
Feature-specific documentation covering user-facing functionality:

- **[agents.md](features/agents.md)** - Autonomous agents: schema, cron scheduling, execution flow, approval workflow, budgets, Command Center UI, agent-to-agent communication, routing race prevention
- **[agent-tools.md](features/agent-tools.md)** - Tool binding and permissions (always-bound vs `ALWAYS_SAFE_TOOLS`, three layers), search provider chain, tool security, adding a new tool, K/V store, browser tool (action batches, page state)
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
- **[ui-features.md](features/ui-features.md)** - Input toolbar, conversation management, deep linking, version banner, color scheme, clipboard operations, sports training programs UI

### Architecture (`architecture/`)
System design and architectural decisions:

- **[authentication.md](architecture/authentication.md)** - Google Sign-In, JWT token handling, token refresh, @require_auth decorator
- **[database.md](architecture/database.md)** - Blob storage, connection pooling, indexes, performance monitoring, vacuum, backup, best practices
- **[api-design.md](architecture/api-design.md)** - OpenAPI documentation and type generation, route organization, request validation (including magic bytes)
- **[rate-limiting.md](architecture/rate-limiting.md)** - Flask-Limiter categories, key strategy, headers, decorators
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
- **[deployment.md](deployment.md)** - Production operations: systemd maintenance timers (backup, vacuum, currency, memory defrag), nginx reverse-proxy config, log rotation
- **[testing.md](testing.md)** - Testing index: commands, TDD, isolation and mocking rules, flaky-test prevention, lint/coverage/audit gates
- **[testing/backend.md](testing/backend.md)** - pytest layout, fixtures, chat-path mock return shapes, writing backend tests
- **[testing/frontend.md](testing/frontend.md)** - Vitest unit/component tests, Playwright E2E, the E2E mock server and `/test/*` endpoints, planner tests
- **[testing/e2e-reliability.md](testing/e2e-reliability.md)** - Starved-runner signature, visual flakes as state races, CI first-run reliability pass, E2E gotchas
- **[testing/visual.md](testing/visual.md)** - Visual regression tests: darwin vs Linux baselines, regeneration via Docker or CI
- **[testing/evals.md](testing/evals.md)** - Agent behavior evals: golden cases + LLM judge (`make eval`), when to run, case authoring
- **[logging.md](logging.md)** - Structured logging (backend JSON format, frontend logger utility), request IDs, logging guidelines
- **[conventions.md](conventions.md)** - Code quality guidelines, refactoring patterns, file size rules
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

### When to Update Documentation

**Update CLAUDE.md when:**
- Adding new common tasks (e.g., new Make targets)
- Changing development workflow
- Updating quick reference commands
- Adding code style guidelines that apply project-wide

**Update feature docs when:**
- Implementing new features
- Changing how existing features work
- Adding configuration options
- Modifying API endpoints
- Changing UI behavior

**Update architecture docs when:**
- Changing authentication/authorization
- Modifying database schema
- Adding new validation rules
- Changing error handling patterns
- Updating rate limits

**Update UI docs when:**
- Changing scroll behavior
- Adding new mobile/PWA features
- Modifying CSS architecture
- Adding new component patterns

### How to Update Documentation

1. **Find the right doc** - Check this index
2. **Update inline** - Documentation is next to code for easy maintenance
3. **Update "See Also" sections** - Keep cross-references current
4. **Test examples** - Verify code examples still work
5. **Keep CLAUDE.md lean** - Detailed info goes in `docs/`, not here

### Adding New Features - Documentation Checklist

When implementing a significant new feature:

1. ✅ Add feature documentation to appropriate `docs/features/` file
2. ✅ Update architecture docs if system design changes
3. ✅ Add testing section to feature doc
4. ✅ Update `docs/README.md` index if adding new doc
5. ✅ Add a pointer from AGENTS.md only for a new everyday command or hard rule
6. ✅ Update `.env.example` if adding environment variables
7. ✅ Update README.md if feature is user-facing

### Style Guide

- Use clear headings with `#`, `##`, `###` hierarchy
- Include code examples with syntax highlighting (` ```python ` or ` ```typescript `)
- Link to source files with relative paths (`../../src/...`)
- Use tables for structured data (e.g., configuration options, API endpoints)
- Add "See Also" sections at the end linking to related docs
- Keep line length reasonable (~120 chars max) for readability

### Quick Rules

1. **Keep it DRY**: Don't duplicate content between files. Use links to reference related information.
2. **Use relative links**: Link to other docs using relative paths (e.g., `[Database](architecture/database.md)`)
3. **Add "See Also" sections**: Help readers find related content
4. **Include code examples**: Show don't tell - provide concrete examples
5. **Keep AGENTS.md lean**: add a pointer only for a new everyday command or hard rule

## Contributing

When adding new features:
1. Update or create the appropriate documentation file in the relevant directory
2. Add a link to it in this README
3. Add a pointer from [../CLAUDE.md](../CLAUDE.md) if it's a common task
4. Ensure all internal links work correctly
5. Keep pages under ~500 lines - split by subsystem rather than growing one
6. Link checks run in `tests/unit/test_docs_links.py`
