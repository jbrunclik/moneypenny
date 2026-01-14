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
├── web/                          # Vite + TypeScript frontend (not `frontend/` - allows `ios/`, `android/` later)
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
- [agent/](src/agent/) - LangGraph agent with Gemini integration (split into focused modules):
  - [chat_agent.py](src/agent/chat_agent.py) - Re-exports for backward compatibility
  - [agent.py](src/agent/agent.py) - ChatAgent class and title generation
  - [graph.py](src/agent/graph.py) - LangGraph state machine and nodes
  - [prompts.py](src/agent/prompts.py) - System prompts and user context
  - [content.py](src/agent/content.py) - Content extraction utilities
  - [tool_results.py](src/agent/tool_results.py) - Tool result capture
  - [tool_display.py](src/agent/tool_display.py) - Tool metadata for UI
- [tools/](src/agent/tools/) - Agent tools (web_search, generate_image, execute_code, todoist, google_calendar, retrieve_file)
- [models/](src/db/models/) - Database models and operations (split by entity)
- [main.ts](web/src/main.ts) - Frontend entry point (minimal, delegates to core modules)
- [core/](web/src/core/) - Core frontend modules (split from main.ts):
  - [init.ts](web/src/core/init.ts) - App initialization, login overlay, theme
  - [conversation.ts](web/src/core/conversation.ts) - Conversation CRUD, selection, temp IDs
  - [messaging.ts](web/src/core/messaging.ts) - Message sending, streaming, batch mode
  - [planner.ts](web/src/core/planner.ts) - Planner navigation and management
  - [search.ts](web/src/core/search.ts) - Search result handling and navigation
  - [tts.ts](web/src/core/tts.ts) - Text-to-speech functionality
  - [toolbar.ts](web/src/core/toolbar.ts) - Toolbar buttons and state
  - [gestures.ts](web/src/core/gestures.ts) - Touch gestures and swipe handling
  - [file-actions.ts](web/src/core/file-actions.ts) - File download, preview, clipboard
  - [events.ts](web/src/core/events.ts) - Event listeners and message handlers
  - [sync-banner.ts](web/src/core/sync-banner.ts) - New messages available banner
- [messages/](web/src/components/messages/) - Message display components (split into focused modules):
  - [render.ts](web/src/components/messages/render.ts) - Message rendering (HTML generation, markdown)
  - [streaming.ts](web/src/components/messages/streaming.ts) - Streaming message state and updates
  - [attachments.ts](web/src/components/messages/attachments.ts) - File attachments display (images, documents)
  - [actions.ts](web/src/components/messages/actions.ts) - Message action buttons (copy, delete, speak, sources)
  - [pagination.ts](web/src/components/messages/pagination.ts) - Older/newer messages loading via infinite scroll
  - [orientation.ts](web/src/components/messages/orientation.ts) - Orientation change handling for scroll
  - [loading.ts](web/src/components/messages/loading.ts) - Loading indicators
  - [utils.ts](web/src/components/messages/utils.ts) - Shared utilities (time formatting, ID updates)
- [store.ts](web/src/state/store.ts) - Zustand state management

API routes are organized by feature in [src/api/routes/](src/api/routes/) (11 modules, 43 endpoints). See [api-design.md](docs/architecture/api-design.md#route-organization) for the full list.

## Development Workflow

### Local Development
```bash
make dev  # Runs Flask (8000) + Vite (5173) via concurrently
```
- Uses `concurrently` to run both servers (shows both outputs, kills both on Ctrl+C)
- Vite dev server proxies API calls to Flask
- HMR enabled for instant CSS/JS updates

### Production Build
```bash
make build  # Outputs to static/assets/
```
- Vite generates hashed filenames for cache busting
- Flask reads manifest.json to inject correct asset paths

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

**Function size and complexity:**
- Keep functions small and focused (<50 lines ideal, <100 lines max)
- Functions over 50 lines should be reviewed for extraction opportunities
- Extract testable units into separate functions
- Use section comments in large files (e.g., `# ============ Helper Functions ============`)

**Avoid deep nesting (max 3 levels):**
- Deeply nested code (4+ levels of indentation) is hard to read, test, and maintain
- Use early returns to reduce nesting: `if (error) return;` instead of `if (!error) { ... }`
- Extract nested logic into helper functions with descriptive names
- Use guard clauses at function start for validation

**Extract helpers when you see:**
- Deeply nested code (3+ levels of if/for/try)
- Repeated logic patterns (DRY principle)
- Code that's hard to test in isolation
- Long functions that do multiple things
- Complex conditionals that could be named

**Refactoring patterns:**
- **State encapsulation**: Group related variables into a class/interface (e.g., `_StreamContext`, `StreamingState`)
- **Handler extraction**: Move event handlers to separate named functions
- **Parser helpers**: Extract parsing/validation logic into reusable functions
- **Choreography helpers**: Extract complex async/callback sequences into named functions

### File Size Guidelines (for LLM Context)

**Keep files under 500 lines** - Large files are difficult for LLMs to process effectively:
- Files over 500 lines should be split into focused modules
- Split by feature/responsibility, not by type (e.g., `conversation.ts`, `messaging.ts`, not `handlers.ts`, `utils.ts`)
- Each module should have a single, clear purpose

**When to split a file:**
- File exceeds 500 lines
- File has multiple unrelated responsibilities
- You find yourself using section comments to organize code
- Testing becomes difficult due to too many concerns

**How to split:**
1. Identify logical groupings by feature/responsibility
2. Create new modules in a subdirectory (e.g., `core/`, `routes/`, `models/`)
3. Move code to new modules with clear exports
4. Update imports across the codebase - no backward compatibility re-exports
5. Run linting and tests to verify

**Examples of successful splits:**
- `src/api/routes.py` (1500+ lines) → `src/api/routes/` (11 focused modules)
- `src/agent/chat_agent.py` (800+ lines) → `src/agent/` (7 focused modules)
- `src/db/models.py` (600+ lines) → `src/db/models/` (4 focused modules)
- `web/src/main.ts` (3100+ lines) → `web/src/core/` (11 focused modules)
- `web/src/components/Messages.ts` (1100+ lines) → `web/src/components/messages/` (9 focused modules)

### Frontend Patterns

**State management**: Use [Zustand](https://github.com/pmndrs/zustand) (lightweight, TypeScript-first). Avoid custom state management or Redux.

**Event delegation**: Use event delegation for dynamic content instead of inline `onclick` handlers (iOS Safari has issues with inline handlers on dynamically created elements).

**DOM manipulation**:
- Use `textContent` for plain text, `clearElement()` from [dom.ts](web/src/utils/dom.ts) to clear content
- innerHTML is acceptable for: SVG icons from [icons.ts](web/src/utils/icons.ts), markdown from `renderMarkdown()`, complex HTML structures
- Centralize SVG icons in [icons.ts](web/src/utils/icons.ts) - prevents duplication, single source of truth

**Named constants**: Use `DEFAULT_CONVERSATION_TITLE` from [api.ts](web/src/types/api.ts) instead of hardcoding `'New Conversation'`.

## Pre-Commit Checklist

**Before committing any changes, you MUST run:**

```bash
make lint   # Run all linters (ruff, mypy, eslint)
make test   # Run all tests
```

Both commands must pass without errors. If linting fails, run `make lint-fix` to auto-fix issues where possible.

**Running E2E tests:**
E2E tests can occasionally hang due to browser automation issues. Always run with a timeout:
```bash
cd web && timeout 600 npx playwright test  # 10 minute timeout
```

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

## Related Files

- [docs/README.md](docs/README.md) - Documentation index
- [TODO.md](TODO.md) - Memory bank for planned work
- [README.md](README.md) - User-facing documentation
