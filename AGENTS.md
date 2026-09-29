# Moneypenny - Claude Context

Moneypenny is a family AI assistant: a Flask + LangGraph backend (Gemini) and a
vanilla TypeScript + Vite + Zustand frontend, on SQLite. It is used daily in
production, so main must always be deployable.

> `CLAUDE.md` is a symlink to this file (`AGENTS.md`).

Durable knowledge lives in [docs/](docs/) (index: [docs/README.md](docs/README.md)) —
check the relevant page before an unfamiliar task, and update it when you learn a
new pattern or pitfall. Path-scoped conventions in [.claude/rules/](.claude/rules/)
load automatically (API, agent, evals, frontend, migrations, programs, tests).

## Commands

- `make setup` — venv + deps; `make dev` — Flask (8000) + Vite (5173) with HMR
- `make build` — production frontend build into `static/assets/`
- `make lint` — ruff + mypy (src, evals) + tsc + eslint (web src and tests)
- `make test` — backend tests; `make test-all` — backend + frontend (E2E rebuilds first)
- `make pre-commit` — lint + test-all
- `make eval` — agent-behavior evals against the live API (costs money; report the cost)
- `make migration NAME=...`, `make openapi`, `make types` (TypeScript types from OpenAPI)
- `make sandbox-image`, `make browser-setup`, `make audit`; `make` lists everything

## Hard rules

- **The repo is public.** Never write infrastructure details (hostnames, ports,
  server topology, deploy commands naming them) into tracked files or commit
  messages — say "the production host".
- **Check exit codes directly.** Never judge `make lint`/`mypy`/`pytest` through a
  `grep`/`tail` pipe in an `&&` chain (the pipe masks the exit code; this has
  shipped broken commits). Redirect to a log and branch on `$?`.
- **Before committing:** `make lint` and the full suite (`make test-all`, or
  `make pre-commit`) green in-session.
- **TDD for bug fixes:** failing test first → fix → full suite.
- **E2E runs the last `make build`**, not your source.
- **Test UI changes on desktop and mobile** (768px breakpoint).
- **Conventional Commits:** `type(scope): description` (`feat`, `fix`, `docs`,
  `style`, `refactor`, `test`, `chore`).

## Workflow

`/new-feature` (superpowers brainstorming → TDD → review → docs) and `/fix-bug`
(systematic debugging → failing test first) wire the `superpowers` skills to this
repo. `/regen-baselines` regenerates the Linux visual baselines CI compares
against. Agents in `.claude/agents/`: `test-writer`, `e2e-debugger`, `docs-updater`.

Hooks: `PostToolUse` formats edited files (ruff format + fixes, keeping unused
imports; eslint --fix). `PreToolUse` blocks hand-edits to generated files
(`web/src/types/generated-api.ts`, `static/openapi.json`).

## Layout

- `src/` — `api/routes/` (REST by feature), `api/schemas/` (Pydantic by feature; source of
  the OpenAPI spec), `agent/` (graph, prompts in `prompt_texts/`, `tools/`),
  `db/models/` (SQL lives only here), `auth/`, `utils/`, `config.py` (all env vars
  and model definitions).
- `web/src/` — `core/` (messaging, conversation, sync), `components/`,
  `state/store.ts` (Zustand), `api/client.ts`, `types/`, `styles/`.
- `tests/` (backend unit + integration, `e2e-server.py`), `web/tests/` (unit,
  component, E2E, visual), `evals/` (cases + integration fakes), `migrations/` (yoyo).

## Code conventions

- Type hints everywhere (mypy strict); TypeScript strict.
- Functions < 50 lines ideal, < 100 max; nesting ≤ 3; files ≤ 500 lines, split by
  responsibility. No backward-compatibility re-exports when splitting.
- True constants in `constants.{ts,py}`, tunables in `config.{ts,py}`;
  `SCREAMING_SNAKE_CASE` with units (`_MS`, `_SECONDS`, `_PX`, `_BYTES`).
- New env var: add to `src/config.py` with a default, to `.env.example`, and to the
  relevant `docs/features/` page.
- Details and examples: [docs/conventions.md](docs/conventions.md).

See also [TODO.md](TODO.md) (planned work) and [README.md](README.md) (user docs).
