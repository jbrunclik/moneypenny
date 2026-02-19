# AI Chatbot - Claude Context

This file contains context for Claude Code to work effectively on this project.

> **Note**: `CLAUDE.md` is a symlink to this file (`AGENTS.md`). Both names point to the same content.

**For detailed documentation, see the [docs/](docs/) directory.**

## Quick Reference

- **Dev**: `make dev` (runs Flask + Vite concurrently)
- **Build**: `make build` (production build)
- **Lint**: `make lint` (ruff + mypy + eslint)
- **Test**: `make test-all` (run all tests - backend + frontend)
- **Pre-commit**: `make pre-commit` (lint + test-all + security scan)
- **Setup**: `make setup` (venv + deps)
- **Sandbox**: `make sandbox-image` (build custom Docker image for code execution)
- **OpenAPI**: `make openapi` (export OpenAPI spec)
- **Types**: `make types` (generate TypeScript types from OpenAPI)
- **Audit**: `make audit` (dependency vulnerability scan)
- **Help**: `make` (show all targets)

## Claude Code Workflow

Follow this development cycle for all non-trivial changes:

1. **Plan** - Enter plan mode for features, use `/fix-bug` for TDD bug fixes, use `/new-feature` for feature workflows
2. **Implement** - Write code following project conventions
3. **Review** - Use `code-reviewer` agent proactively after significant changes
4. **Pre-commit** - MUST use `pre-commit` agent before every commit
5. **Commit** - Conventional Commits format: `type(scope): description`
6. **Docs** - Use `docs-updater` agent after features or architectural changes

### Available Agents (`.claude/agents/`)

| Agent | When to use | Trigger |
|-------|-------------|---------|
| `code-reviewer` | After significant features or substantial code changes | Proactive |
| `pre-commit` | Before EVERY commit | Required |
| `api-endpoint` | When adding new REST API endpoints | On demand |
| `docs-updater` | After features or architectural changes | Proactive |
| `migration-creator` | When adding tables, columns, or indexes | On demand |
| `test-writer` | TDD bug fixes, adding test coverage | On demand |
| `e2e-debugger` | When E2E tests fail or are flaky | On demand |

### Available Commands (`.claude/commands/`)

- `/fix-bug` - TDD bug fix workflow (test first, then fix)
- `/new-feature` - Feature implementation workflow (plan, implement, test, review)

### Hooks

A `PostToolUse` hook auto-formats files after every Edit/Write:
- Python files: `ruff format` + `ruff check --fix`
- TypeScript files: `eslint --fix`

This eliminates manual formatting cycles. See `.claude/hooks/auto-format.sh`.

### Memory

Project memory is at `memory/MEMORY.md` with topic files (`testing.md`, `streaming.md`, `frontend.md`).
- Check memory before starting unfamiliar tasks
- Update memory after discovering new patterns or pitfalls

## Project Structure

```
ai-chatbot/
├── src/                          # Flask backend
│   ├── app.py                    # Flask entry point
│   ├── config.py                 # Environment config
│   ├── auth/                     # Authentication (JWT, Google, Todoist, Calendar OAuth)
│   ├── api/                      # REST endpoints, validation, errors
│   │   └── routes/               # 11 modules, 43 endpoints (organized by feature)
│   ├── agent/                    # LangGraph agent with Gemini + tools
│   │   └── tools/                # web_search, generate_image, execute_code, todoist, etc.
│   ├── db/                       # SQLite: User, Conversation, Message
│   │   └── models/               # Split by entity
│   └── utils/                    # Images, costs, logging, files
├── web/                          # Vite + TypeScript frontend
│   └── src/
│       ├── main.ts               # Entry point (delegates to core/)
│       ├── core/                  # 11 core modules (conversation, messaging, etc.)
│       ├── components/            # UI modules (messages/, etc.)
│       ├── types/                 # TypeScript interfaces
│       ├── api/client.ts          # Typed fetch wrapper
│       ├── state/store.ts         # Zustand store
│       ├── utils/                 # DOM, markdown, icons, logger
│       └── styles/                # CSS (modular structure)
├── tests/                        # Backend tests (unit, integration)
├── web/tests/                    # Frontend tests (unit, component, E2E, visual)
├── migrations/                   # Database migrations (yoyo, 27 migrations)
├── docs/                         # Detailed documentation
└── .claude/                      # Claude Code config (agents, commands, hooks)
```

## Key Files

- [config.py](src/config.py) - All env vars, model definitions
- [routes/](src/api/routes/) - API endpoints by feature (see [api-design.md](docs/architecture/api-design.md))
- [schemas.py](src/api/schemas.py) - Pydantic request/response schemas
- [agent/](src/agent/) - LangGraph agent: [agent.py](src/agent/agent.py), [graph.py](src/agent/graph.py), [prompts.py](src/agent/prompts.py), [content.py](src/agent/content.py), [history.py](src/agent/history.py)
- [tools/](src/agent/tools/) - Agent tools
- [models/](src/db/models/) - Database models and operations
- [core/](web/src/core/) - Frontend core modules
- [messages/](web/src/components/messages/) - Message display components
- [store.ts](web/src/state/store.ts) - Zustand state management

## Development Workflow

### Local Development
```bash
make dev  # Runs Flask (8000) + Vite (5173) via concurrently
```
- Vite dev server proxies API calls to Flask
- HMR enabled for instant CSS/JS updates

### Production Build
```bash
make build  # Outputs to static/assets/
```

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

### Code Quality Rules

- Functions: <50 lines ideal, <100 lines max
- Nesting: max 3 levels (use early returns and guard clauses)
- Files: max 500 lines (split by feature/responsibility, not by type)
- No backward compatibility re-exports when splitting files
- See [docs/conventions.md](docs/conventions.md) for detailed patterns and examples

### Frontend Patterns

- **State management**: [Zustand](https://github.com/pmndrs/zustand) (not Redux or custom)
- **Event delegation**: For dynamic content (not inline `onclick` - iOS Safari issues)
- **DOM**: `textContent` for plain text, `clearElement()` from [dom.ts](web/src/utils/dom.ts)
- **Icons**: Centralized in [icons.ts](web/src/utils/icons.ts)
- **Named constants**: `DEFAULT_CONVERSATION_TITLE` from [api.ts](web/src/types/api.ts)

## Pre-Commit Checklist

**Before committing, use the `pre-commit` agent** or run manually:

```bash
make lint   # Run all linters (ruff, mypy, eslint)
make test   # Run all backend tests
```

Both must pass. Use `make lint-fix` for auto-fixable issues.

**E2E tests** - always run with timeout: `cd web && timeout 600 npx playwright test`

**Zero tolerance for flaky tests** - investigate root causes, don't just re-run.

**TDD for bug fixes**: failing test first -> fix -> verify -> full suite.

## Common Tasks

### Add a new API endpoint
Use the `api-endpoint` agent, or manually add to the appropriate module in [src/api/routes/](src/api/routes/). Use `@api.output()` for response schema.

### Add a new tool to the agent
Create file in [tools/](src/agent/tools/), add `@tool` decorator, register in [tools/__init__.py](src/agent/tools/__init__.py). See [docs/features/agents.md](docs/features/agents.md#adding-a-new-tool).

### Add a database migration
Use the `migration-creator` agent, or create file in [migrations/](migrations/) following `NNNN_description.py` pattern.

### Change available models
Edit [config.py](src/config.py) `MODELS` dict.

### Add a new UI component
1. Create TypeScript file in `web/src/components/`
2. Export init function and render functions
3. Import and wire in `main.ts`

### Add new environment variables
1. Add to [config.py](src/config.py) with a sensible default
2. **Update [.env.example](.env.example)**
3. Document in the relevant `docs/features/` file

## Related Files

- [docs/README.md](docs/README.md) - Documentation index
- [docs/conventions.md](docs/conventions.md) - Detailed code quality patterns and file size guidelines
- [TODO.md](TODO.md) - Memory bank for planned work
- [README.md](README.md) - User-facing documentation
