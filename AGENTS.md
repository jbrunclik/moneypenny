# Moneypenny - Claude Context

This file contains context for Claude Code to work effectively on this project.

> **Note**: `CLAUDE.md` is a symlink to this file (`AGENTS.md`). Both names point to the same content.

**For detailed documentation, see the [docs/](docs/) directory.** Area-specific
conventions live in [.claude/rules/](.claude/rules/) and load automatically when you
work on matching files (API, agent, frontend, migrations, programs, tests).

## Quick Reference

- **Dev**: `make dev` (runs Flask + Vite concurrently)
- **Build**: `make build` (production build)
- **Lint**: `make lint` (ruff + mypy + eslint)
- **Test**: `make test-all` (run all tests - backend + frontend)
- **Evals**: `make eval` (agent behavior evals, live API - run around prompt/tool changes)
- **Pre-commit**: `make pre-commit` (lint + test-all + security scan)
- **Setup**: `make setup` (venv + deps)
- **Sandbox**: `make sandbox-image` (build custom Docker image for code execution)
- **Browser**: `make browser-setup` (install Playwright + Chromium for browser tool)
- **OpenAPI**: `make openapi` (export OpenAPI spec)
- **Types**: `make types` (generate TypeScript types from OpenAPI)
- **Audit**: `make audit` (dependency vulnerability scan)
- **Help**: `make` (show all targets)

## Claude Code Workflow

Follow this development cycle for all non-trivial changes:

1. **Plan** - Use `superpowers:brainstorming` (via `/new-feature`) for features, `/fix-bug` for TDD bug fixes
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

- `/new-feature` - Feature workflow: defers to `superpowers:brainstorming` (design + approval) then TDD, review, docs
- `/fix-bug` - Bug-fix workflow: defers to `superpowers:systematic-debugging` (root cause first) + TDD (failing test first)
- `/regen-baselines` - Regenerate Linux visual-regression baselines via the CI dispatch workflow and commit them (use after any intentional UI change)

The `superpowers` process skills (brainstorming, test-driven-development,
systematic-debugging, verification-before-completion) are the backbone; the
commands wire them to this project's conventions.

### Hooks

- **`PostToolUse`** auto-formats files after every Edit/Write (Python: `ruff format` + `ruff check --fix`; TypeScript: `eslint --fix`). See `.claude/hooks/auto-format.sh`.
- **`PreToolUse`** blocks hand-edits to generated files (`web/src/types/generated-api.ts`, `static/openapi.json`). See `.claude/hooks/block-generated.sh`.

### Project Knowledge & Docs

Durable engineering knowledge — architecture, conventions, feature internals, and hard-won pitfalls — lives in [docs/](docs/) (indexed by [docs/README.md](docs/README.md)).
- Check the relevant `docs/` page before starting an unfamiliar task.
- After discovering a new pattern or pitfall, update the appropriate `docs/` page so the knowledge is shared with all collaborators and agents (don't leave it only in a personal/agent scratch memory).

## Project Structure

- `src/` — Flask backend: `api/routes/` (REST endpoints by feature), `agent/` (LangGraph agent + `tools/`), `db/models/`, `auth/`, `utils/`, `config.py`.
- `web/src/` — Vite + TypeScript frontend: `core/`, `components/`, `state/store.ts` (Zustand), `api/client.ts`, `types/`, `styles/`.
- `tests/` + `web/tests/` — backend and frontend tests (unit, integration, E2E, visual).
- `migrations/` — yoyo DB migrations. `docs/` — detailed docs. `.claude/` — agents, commands, hooks, rules.

Detailed per-area conventions load by path from `.claude/rules/`; deeper reference lives in `docs/`.

## Key Files

- [config.py](src/config.py) - All env vars, model definitions
- [routes/](src/api/routes/) - API endpoints by feature (see [api-design.md](docs/architecture/api-design.md))
- [schemas.py](src/api/schemas.py) - Pydantic request/response schemas
- [agent/](src/agent/) - LangGraph agent: [agent.py](src/agent/agent.py), [graph.py](src/agent/graph.py), [prompts.py](src/agent/prompts.py), [content.py](src/agent/content.py), [history.py](src/agent/history.py)
- [tools/](src/agent/tools/) - Agent tools (including [browser.py](src/agent/tools/browser.py) for Playwright-based browsing)
- [models/](src/db/models/) - Database models and operations
- [core/](web/src/core/) - Frontend core modules
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

### Code Quality Rules

- Functions: <50 lines ideal, <100 lines max
- Nesting: max 3 levels (use early returns and guard clauses)
- Files: max 500 lines (split by feature/responsibility, not by type)
- No backward compatibility re-exports when splitting files
- See [docs/conventions.md](docs/conventions.md) for detailed patterns and examples

### Add new environment variables
1. Add to [config.py](src/config.py) with a sensible default
2. **Update [.env.example](.env.example)**
3. Document in the relevant `docs/features/` file

## Pre-Commit Checklist

**Before committing, use the `pre-commit` agent** or run manually:

```bash
make lint   # Run all linters (ruff, mypy, eslint)
make test   # Run all backend tests
```

Both must pass. Use `make lint-fix` for auto-fixable issues.

**Check exit codes directly** - never judge `make lint`/`mypy`/`pytest` by piping through `grep`/`tail` in `&&` chains (the pipe masks the exit code; this has shipped broken commits). Redirect to a log and branch on `$?`.

**TDD for bug fixes**: failing test first -> fix -> verify -> full suite.

(E2E and visual-regression specifics load from [.claude/rules/testing.md](.claude/rules/testing.md) when you touch test files.)

## Related Files

- [.claude/rules/](.claude/rules/) - Path-scoped conventions (API, agent, frontend, migrations, programs, tests)
- [docs/README.md](docs/README.md) - Documentation index
- [docs/conventions.md](docs/conventions.md) - Detailed code quality patterns and file size guidelines
- [TODO.md](TODO.md) - Memory bank for planned work
- [README.md](README.md) - User-facing documentation
