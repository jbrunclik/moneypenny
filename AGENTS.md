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
- `make lock` — after editing `requirements.in` (runtime ranges) or `requirements-dev.in` (tools); the `.txt` files are the generated locks
- `make sandbox-image`, `make browser-setup`, `make audit`; `make` lists everything

## Hard rules

The full rule set, with what enforces each rule, is in
[docs/conventions.md](docs/conventions.md). These apply to every session:

- **The repo is public.** Never write infrastructure details (hostnames, ports,
  server topology, deploy commands naming them) into tracked files or commit
  messages — say "the production host" (S9).
- **Check exit codes directly.** Never judge `make lint`/`mypy`/`pytest` through a
  `grep`/`tail` pipe in an `&&` chain (the pipe masks the exit code; this has
  shipped broken commits). Redirect to a log and branch on `$?` (A3).
- **Before committing:** `make lint` and the full suite (`make test-all`, or
  `make pre-commit`) green in-session. Nothing gates `main` or the deploy, so
  this is the gate (A3).
- **TDD for bug fixes:** failing test first → fix → full suite (T1).
- **E2E runs the last `make build`**, not your source (T10).
- **Test UI changes on desktop and mobile** (768px breakpoint) (T11).
- **Conventional Commits:** `type(scope): description` — a hook rejects others (A2).

## Parallel sessions

Several agent sessions often work in this checkout at once (A1):

- **Stage explicit paths only.** Never `git add -A`/`.`/`-u`, `git commit -a`,
  `git stash`, `git checkout .`/`git restore .`, `git reset --hard` or
  `git clean -f` — they take or discard other sessions' work. A hook
  blocks them. To undo your own change, restore that file by path.
- **Leave files you didn't change alone** — unknown modifications in
  `git status` belong to another session; don't commit or revert them.
- **Run E2E on your own port** (`E2E_PORT=8011 make test-fe-e2e`) when another
  session might be testing, and stop a server via its PID file
  (`.e2e-server-<port>.pid`), never by killing whatever listens on a port.
  `make build` replaces `static/assets` for everyone: for long UI work use a
  worktree (`superpowers:using-git-worktrees`, under `.claude/worktrees/`).
- **New migration while another session might add one:** check the highest
  number on `main` right before committing; two sessions both creating the
  same `NNNN_` break startup.

## Workflow

Commands in `.claude/commands/` wire the `superpowers` skills to this repo:
`/new-feature` (brainstorming → TDD → review → docs), `/fix-bug` (systematic
debugging → failing test first), `/new-endpoint` (schema → route → OpenAPI →
client → tests), `/new-tool` (agent tool checklist), `/split-file`,
`/update-deps`, `/regen-baselines` (the Linux visual baselines CI compares
against), `/product-review` (the regular review in
[docs/regular-review.md](docs/regular-review.md)). Agents in `.claude/agents/`: `test-writer`, `e2e-debugger`,
`docs-updater`.

Hooks: `PostToolUse` formats edited files (ruff format + fixes, keeping unused
imports; eslint --fix; Prettier for CSS/YAML/JSON). `PreToolUse` blocks hand-edits to generated files
(`web/src/types/generated-api.ts`, `static/openapi.json`) and sweeping or
non-conventional git commands (`guard-git.py`).

## Layout

- `src/` — `api/routes/` (REST by feature), `api/schemas/` (Pydantic by feature; source of
  the OpenAPI spec), `agent/` (graph, prompts in `prompt_texts/`, `tools/`),
  `services/` (DB-backed services), `db/models/` (SQL lives only here), `auth/`,
  `utils/` (pure helpers), `config.py` (all env vars and model definitions).
- `web/src/` — `core/` (messaging, conversation, sync), `components/`,
  `state/store.ts` (Zustand, slices in `state/slices/`), `api/` (one module per
  domain), `types/`, `styles/`.
- `tests/` (backend unit + integration, `e2e-server.py` + `e2e_server/`), `web/tests/` (unit,
  component, E2E, visual), `evals/` (cases + integration fakes), `migrations/` (yoyo).

## Code conventions

Summary — the rules, their IDs and enforcers are in [docs/conventions.md](docs/conventions.md):

- Type hints everywhere (mypy strict); TypeScript strict.
- Functions < 50 lines ideal, < 100 max; nesting ≤ 3. Split files by
  responsibility, not line count. No backward-compatibility re-exports.
- Imports point down the layers (routes → helpers → agent → services → db → utils;
  core → components → state → api → utils).
- True constants in `constants.{ts,py}`, tunables in `config.{ts,py}`;
  `SCREAMING_SNAKE_CASE` with units (`_MS`, `_SECONDS`, `_PX`, `_BYTES`).
- New env var: add to `src/config.py` with a default, to `.env.example`, and to the
  relevant `docs/features/` page.
- Logs: user ids, never emails; truncated excerpts that help improve the agent
  are fine, full conversations never.

See also [TODO.md](TODO.md) (planned work) and [README.md](README.md) (user docs).
