# AI Chatbot - Claude Context

This file contains context for Claude Code to work effectively on this project.

> **Note**: `CLAUDE.md` is a symlink to this file (`AGENTS.md`). This allows the file to be referenced as either `CLAUDE.md` (for Claude Code) or `AGENTS.md` (the canonical name). Both names point to the same content.

**For detailed documentation, see the [docs/](docs/) directory.** This file provides a quick reference and pointers to detailed guides.

## Quick Reference

- **Dev**: `make dev` (runs Flask + Vite concurrently)
- **Build**: `make build` (production build)
- **Lint**: `make lint` (ruff + mypy + eslint)
- **Test**: `make test-all` (run all tests - backend + frontend)
- **Setup**: `make setup` (venv + deps)
- **Sandbox**: `make sandbox-image` (build custom Docker image for code execution)
- **OpenAPI**: `make openapi` (export OpenAPI spec)
- **Types**: `make types` (generate TypeScript types from OpenAPI)
- **Help**: `make` (show all targets)

## Project Structure

```
ai-chatbot/
├── src/                          # Flask backend
│   ├── app.py                    # Flask entry point
│   ├── config.py                 # Environment config
│   ├── auth/                     # Authentication (JWT, Google, Todoist, Calendar OAuth)
│   ├── api/                      # REST endpoints, validation, errors
│   ├── agent/                    # LangGraph agent with Gemini + tools
│   ├── db/                       # SQLite: User, Conversation, Message
│   └── utils/                    # Images, costs, logging, files
├── web/                          # Vite + TypeScript frontend
│   └── src/
│       ├── main.ts               # Entry point
│       ├── types/                # TypeScript interfaces
│       ├── api/client.ts         # Typed fetch wrapper
│       ├── auth/google.ts        # Google Sign-In, JWT
│       ├── state/store.ts        # Zustand store
│       ├── components/           # UI modules
│       ├── utils/                # DOM, markdown, icons, logger
│       └── styles/               # CSS (modular structure)
├── static/                       # Build output + PWA assets
├── tests/                        # Backend tests (unit, integration)
├── web/tests/                    # Frontend tests (unit, component, E2E, visual)
├── migrations/                   # Database migrations (yoyo)
├── scripts/                      # Maintenance scripts
├── systemd/                      # Systemd services (backup, vacuum, etc.)
└── docs/                         # Detailed documentation (see below)
```

## Key Files

- [config.py](src/config.py) - All env vars, model definitions
- [routes/](src/api/routes/) - API endpoints organized by feature (see [api-design.md](docs/architecture/api-design.md))
- [schemas.py](src/api/schemas.py) - Pydantic request/response schemas
- [chat_agent.py](src/agent/chat_agent.py) - LangGraph graph, Gemini integration
- [tools/](src/agent/tools/) - Agent tools (web_search, generate_image, execute_code, todoist, google_calendar, retrieve_file)
- [models.py](src/db/models.py) - Database schema and operations
- [main.ts](web/src/main.ts) - Frontend entry point
- [store.ts](web/src/state/store.ts) - Zustand state management

### API Route Organization

Routes are split across 11 focused modules (43 total endpoints):
- [routes/auth.py](src/api/routes/auth.py) - Google authentication (4 routes)
- [routes/todoist.py](src/api/routes/todoist.py) - Todoist integration (4 routes)
- [routes/calendar.py](src/api/routes/calendar.py) - Google Calendar (7 routes)
- [routes/conversations.py](src/api/routes/conversations.py) - Conversation CRUD (9 routes)
- [routes/planner.py](src/api/routes/planner.py) - Planner dashboard (4 routes)
- [routes/chat.py](src/api/routes/chat.py) - Chat endpoints (2 routes)
- [routes/files.py](src/api/routes/files.py) - File serving (2 routes)
- [routes/costs.py](src/api/routes/costs.py) - Cost tracking (4 routes)
- [routes/settings.py](src/api/routes/settings.py) - User settings (2 routes)
- [routes/memory.py](src/api/routes/memory.py) - User memory (2 routes)
- [routes/system.py](src/api/routes/system.py) - Models, config, version, health (5 routes)

Helper modules:
- [helpers/validation.py](src/api/helpers/validation.py) - Common validation patterns
- [helpers/chat_streaming.py](src/api/helpers/chat_streaming.py) - Chat streaming utilities

## Development Workflow

### Local Development
```bash
make dev  # Runs Flask (8000) + Vite (5173) concurrently
```
- Vite dev server proxies API calls to Flask
- HMR enabled for instant CSS/JS updates

### Production Build
```bash
make build  # Outputs to static/assets/
```
- Vite generates hashed filenames for cache busting
- Flask reads manifest.json to inject correct asset paths

## Gemini API Notes

### Models
- `gemini-3-pro-preview` - Complex tasks, advanced reasoning
- `gemini-3-flash-preview` - Fast, cheap (default)

### Response Format
Gemini may return content in various formats. Use `extract_text_content()` in [chat_agent.py](src/agent/chat_agent.py) to normalize.

### Parameters
- `thinking_level`: Controls reasoning (minimal/low/medium/high)
- Temperature: Keep at 1.0 (Gemini 3 default)

## Code Style

- Type hints in all Python code
- TypeScript for all frontend code (strict mode)
- Conventional Commits: `type(scope): description`
  - Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`
- **Test all UI changes on both desktop and mobile** - responsive layout with 768px breakpoint

### Constants and Configuration

- **True constants** (unit conversions): `constants.{ts,py}`
- **Developer-configurable values**: `config.{ts,py}`
- Use `SCREAMING_SNAKE_CASE` with units in the name (`_MS`, `_SECONDS`, `_PX`, `_BYTES`)

### Enums for Categorical Values

Use enums for fixed sets of options. Backend: `str, Enum` in [schemas.py](src/api/schemas.py). Frontend: `as const` pattern in [api.ts](web/src/types/api.ts).

### Code Quality Guidelines

- Keep functions small and focused (<50 lines)
- Extract testable units into separate functions
- Use section comments in large files (e.g., `# ============ Helper Functions ============`)
- Extract helpers when you see deeply nested code, repeated logic, or code that's hard to test

## Pre-Commit Checklist

**Before committing any changes, you MUST run:**

```bash
make lint   # Run all linters (ruff, mypy, eslint)
make test   # Run all tests
```

Both commands must pass without errors. If linting fails, run `make lint-fix` to auto-fix issues where possible.

**Zero tolerance for flaky tests:**
- All tests MUST pass consistently - no intermittent failures
- If a test fails, investigate the root cause; don't just re-run and hope it passes
- When writing assertions on dynamic content, use robust matchers

**When implementing new features:**
- Add tests for new backend code to maintain coverage
- Add E2E tests for significant UI changes

**When fixing bugs (TDD approach):**
1. Write a failing test first that reproduces the bug
2. Run the test to confirm it fails
3. Implement the fix
4. Run the test to confirm it passes
5. Run the full test suite to ensure no regressions

## Common Tasks

### Add a new API endpoint
Add route to the appropriate module in [src/api/routes/](src/api/routes/) (e.g., [routes/conversations.py](src/api/routes/conversations.py) for conversation-related endpoints). Use `@api.output()` decorator for response schema. Routes are organized by feature - see [API Route Organization](#api-route-organization) above.

### Add a new tool to the agent
Create a new file in [tools/](src/agent/tools/) or add to an existing tool module. Add function with `@tool` decorator and register in [tools/__init__.py](src/agent/tools/__init__.py).

### Change available models
Edit [config.py](src/config.py) `MODELS` dict.

### Add a new UI component
1. Create TypeScript file in `web/src/components/`
2. Export init function and render functions
3. Import and wire in `main.ts`

### Add new icons
Add SVG constants to [icons.ts](web/src/utils/icons.ts) and import where needed.

### Add new environment variables
1. Add the variable to [config.py](src/config.py) with a sensible default
2. **Update [.env.example](.env.example)** with the new variable and documentation
3. Document in the relevant feature doc in `docs/features/`
4. If user-facing, document in README.md

### Configure calendar selection
1. Connect Google Calendar in Settings
2. Select which calendars to include in planner context (primary calendar always included)
3. Save selection - dashboard will fetch events from all selected calendars in parallel
4. Calendar labels appear on events from non-primary calendars

---

## Documentation Maintenance

### Documentation Structure

**Note**: This file (`AGENTS.md`) is the canonical documentation. `CLAUDE.md` is a symlink to this file for compatibility with Claude Code. When updating documentation, edit `AGENTS.md` - changes will be reflected in both.

Documentation is organized into focused, discoverable files in the `docs/` directory:

```
docs/
├── README.md                      # Documentation index
├── features/                      # Feature-specific guides
│   ├── chat-and-streaming.md      # Gemini API, streaming, thinking indicator
│   ├── file-handling.md           # Image generation, code execution, uploads
│   ├── voice-and-tts.md           # Speech-to-text and text-to-speech
│   ├── search.md                  # Full-text search with FTS5
│   ├── sync.md                    # Real-time sync across tabs/devices
│   ├── integrations.md            # Todoist and Google Calendar
│   ├── memory-and-context.md      # User memory, custom instructions, anonymous mode
│   ├── cost-tracking.md           # Token costs, image generation costs
│   └── ui-features.md             # Input toolbar, clipboard, conversation mgmt
├── architecture/                  # System design
│   ├── authentication.md          # Google Sign-In, JWT, OAuth
│   ├── database.md                # Schema, blob storage, indexes, performance
│   └── api-design.md              # OpenAPI, rate limiting, validation, errors
├── ui/                            # UI implementation
│   ├── scroll-behavior.md         # Scroll scenarios, auto-scroll, pagination
│   ├── mobile-and-pwa.md          # Touch gestures, iOS gotchas, PWA fixes
│   └── components.md              # CSS architecture, patterns, design system
├── testing.md                     # Test structure, patterns, E2E server
└── logging.md                     # Structured logging (backend and frontend)
```

### When to Update Documentation

**Update CLAUDE.md when:**
- Adding new common tasks (e.g., new Make targets)
- Changing development workflow
- Updating quick reference commands
- Adding code style guidelines that apply project-wide
- Adding preferences or corrections

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

1. **Find the right doc** - Check `docs/README.md` for the index
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
5. ✅ Add pointer to detailed doc from CLAUDE.md (if it's a common task)
6. ✅ Update `.env.example` if adding environment variables
7. ✅ Update README.md if feature is user-facing

### Documentation Style Guide

- Use clear headings with `#`, `##`, `###` hierarchy
- Include code examples with syntax highlighting (` ```python ` or ` ```typescript `)
- Link to source files with relative paths (`../../src/...`)
- Use tables for structured data (e.g., configuration options, API endpoints)
- Add "See Also" sections at the end linking to related docs
- Keep line length reasonable (~120 chars max) for readability

### Finding Documentation

Use the index in [docs/README.md](docs/README.md) to find relevant documentation.

**Quick links to common topics:**
- Chat and streaming → [docs/features/chat-and-streaming.md](docs/features/chat-and-streaming.md)
- File uploads and images → [docs/features/file-handling.md](docs/features/file-handling.md)
- Database and performance → [docs/architecture/database.md](docs/architecture/database.md)
- API design and validation → [docs/architecture/api-design.md](docs/architecture/api-design.md)
- Mobile and PWA → [docs/ui/mobile-and-pwa.md](docs/ui/mobile-and-pwa.md)
- Testing → [docs/testing.md](docs/testing.md)

---

## Preferences & Corrections

When I correct Claude's approach, the reasoning is documented here to prevent repeated mistakes.

### Naming

**Preference**: Use "AI Chatbot" consistently (not "AI Chat")
**Context**: Branding consistency across all UI text, meta tags, and documentation

### Directory Structure

**Preference**: Use `web/` for frontend (not `frontend/`)
**Context**: Leaves room for potential native mobile app later (`ios/`, `android/`)

### State Management

**Preference**: Use Zustand for state management
**Context**: Lightweight, TypeScript-first, simpler than Redux. Avoid custom state management solutions.

### Development Server

**Preference**: Use `concurrently` for running multiple dev servers
**Context**: Background processes are hard to manage. `concurrently` shows both outputs clearly and kills both on Ctrl+C.
**Avoid**: Using `&` or background jobs in Makefile

### UI Patterns

**Preference**: Use event delegation for dynamic elements
**Context**: iOS Safari has issues with inline onclick handlers on dynamically created elements
**Avoid**: Inline `onclick` attributes in template strings

### innerHTML Usage

**Preference**: Minimize innerHTML usage; use `textContent`, `createElement`, or DOM helpers where possible
**Context**: innerHTML parses HTML and can be a security risk if misused. Using DOM methods is more explicit about intent.

**When innerHTML is ACCEPTABLE:**
- Setting SVG icons from [icons.ts](web/src/utils/icons.ts)
- Rendering markdown content from `renderMarkdown()`
- Complex HTML structures that would be cumbersome to build with createElement

**When to AVOID innerHTML:**
- Clearing element content → Use `clearElement(element)` from [dom.ts](web/src/utils/dom.ts)
- Setting plain text → Use `element.textContent = text`

### Icons

**Preference**: Centralize SVG icons in [icons.ts](web/src/utils/icons.ts)
**Context**: Prevents duplication across components
**Avoid**: Inline SVG in template strings

### Constants

**Preference**: Use `DEFAULT_CONVERSATION_TITLE` constant from [api.ts](web/src/types/api.ts)
**Context**: Avoids magic strings
**Avoid**: Hardcoding `'New Conversation'` directly

### Conversation Creation

**Pattern**: Lazy conversation creation - conversations are created locally with `temp-` prefixed ID, only persisted to DB on first message
**Location**: [main.ts](web/src/main.ts) - `createConversation()`, `sendMessage()`, `isTempConversation()`
**Rationale**: Prevents empty conversations from polluting the database

### User Message ID Handling

User messages are initially created with temp IDs (`temp-{timestamp}`) in the frontend. The backend returns the real message ID via:
- **Streaming mode**: `user_message_saved` SSE event
- **Batch mode**: `user_message_id` field in response

Images with temp message IDs are marked with `data-pending="true"` and show `cursor: wait` until the real ID is available.

### Concurrent Request Handling

The app supports multiple active requests across different conversations simultaneously. Requests continue processing in the background even when users switch conversations.

**Key implementation details:**
- Active requests tracked per conversation in `activeRequests` map
- Requests only update UI if their conversation is still current
- Server-side: cleanup threads ensure messages are saved even if client disconnects

### Seamless Conversation Switching

When switching away from a conversation with an active request and back, the UI state is seamlessly restored.

**Key state management:**
- `activeRequests` Map in store tracks content and thinking state per conversation
- `streamingMessageElements` Map in main.ts tracks DOM elements for continued updates
- Streaming context includes `conversationId` to determine whether to clean up

### @require_auth Injects User

The `@require_auth` decorator injects the authenticated `User` as the first argument to route handlers.

**Pattern:**
```python
@api.route("/endpoint", methods=["GET"])
@require_auth
def my_endpoint(user: User) -> dict:
    # user is guaranteed to be a valid User
    return {"user_id": user.id}
```

### Conversation Selection Race Condition

A module-level `pendingConversationId` variable tracks which conversation the user most recently clicked. When an API call completes, we check if it matches - if not, the user navigated elsewhere and we cancel.

### Two-Way File References

The documentation now uses two-way references:
- Feature docs link to implementation files
- This file (CLAUDE.md) provides quick reference and pointers to detailed docs
- This prevents documentation from becoming stale or disconnected from code

---

## Related Files

- [docs/README.md](docs/README.md) - Documentation index
- [TODO.md](TODO.md) - Memory bank for planned work
- [README.md](README.md) - User-facing documentation
