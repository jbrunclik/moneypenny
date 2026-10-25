# Engineering Standards

The canonical home for Moneypenny's architecture and coding rules. Agents are
the main contributors, so every rule here has an ID, one home, and an
enforcer. [AGENTS.md](../AGENTS.md) carries the hard rules that apply to every
session and points here for the rest.

## How the rules work

- **Enforced** rules fail lint, a test, a hook or CI - you find out
  immediately. **Planned** rules are agreed but their check isn't built yet
  (tracked in [TODO.md](../TODO.md), "Enforce the standards"): follow them in
  new code anyway. **Judgment** rules can't be checked mechanically - reviewers
  and agents apply them.
- **Existing violations get a baseline that only shrinks.** A new rule applies
  to new code at once; the cleanup of old code is a TODO item, done
  gradually. Never add to a baseline to get a change through. For ruff the
  baseline is a bare `# noqa: CODE` on the line (Oct 25 2026: 407); a
  deliberate exception carries a reason instead: `# noqa: CODE - <why>`.
  For ESLint it is `web/eslint-suppressions.json` (286): after fixing some,
  `npx eslint src --prune-suppressions` (ESLint fails on stale entries).
- **One home per rule.** Other pages link here instead of restating the rule,
  so it can't drift. To change a rule, edit it here and its enforcer in the
  same commit.
- **No gate before production** (decision, Oct 2026): this is a hobby project
  that iterates fast. Commits go straight to `main` and CI reports after the
  fact; a deploy doesn't wait for CI. That makes the local checks (lint, the
  full suite, hooks) the real gate.

## Rules index

### Security (S)

| ID | Rule | Enforced by |
|----|------|-------------|
| S1 | Production can't start with auth off or an invalid config: `FLASK_ENV` unset means production, `E2E_TESTING` bypasses auth only with `FLASK_ENV=testing`, `create_app()` validates | test (`test_config.py`) |
| S2 | `require_auth` checks `ALLOWED_EMAILS` on every request | test (`test_routes_auth.py`) |
| S3 | The browser tool checks every request against the SSRF blocklist and refuses redirect landings on blocked addresses | test (`test_browser_request_guard.py`) |
| S4 | Every route requires auth or is on the explicit public list | test (`test_route_auth_coverage.py`) |
| S5 | Every outbound call has an explicit timeout, LLM clients included | test (`test_outbound_timeouts.py`; 4 Gemini clients baselined) |
| S6 | Model output never loads external resources by itself (external markdown images render as links; CSP `img-src` allows only the app and Google profile photos) | test (`markdown.test.ts`, `test_security_headers.py`) |
| S7 | Production requires a valid `TOKEN_ENCRYPTION_KEY` | test (`test_config.py`) |
| S8 | Logging follows the [privacy policy below](#logging-and-privacy) | test (`test_log_fields.py`: no email, credential or whole-text fields); judgment for truncation |
| S9 | No secrets or infrastructure details in tracked files or commit messages (the repo is public) | CI (gitleaks + a `FORBIDDEN_PATTERNS` secret scan); gitleaks on commit locally |
| S10 | Public API docs (`/api/docs`, `/api/openapi.json`) are off in production | test (`test_security_headers.py`) |
| S11 | Deploys can't overlap and can be rolled back (lock, previous SHA, backup before migrations, assets swapped without a gap) | `make update` / `make rollback` ([deployment.md](deployment.md#deploying-and-rolling-back)) |
| S12 | Spend of more than $10 per user per day shows that user a banner (something looks off) - never a block, no notification; the admin sees total spend in the app | planned (`/new-feature`) |

### Delivery (P)

| ID | Rule | Enforced by |
|----|------|-------------|
| P1 | Generated files never drift: `static/openapi.json` and `generated-api.ts` match the schemas, `requirements.txt` matches `requirements.in`, `.env.example` lists every config variable | CI (regenerate and diff); test (`test_env_example.py`, 46-name baseline) |
| P2 | Migrations form one chain with unique numbers; each step has a rollback or an `# irreversible:` reason | test (`test_migration_chain.py`) |
| P3 | Dependabot auto-merges patch and minor updates only | workflow + test (`test_dependabot_majors.py`); planned: audit as a merge condition |
| P4 | CI cancels superseded runs, has read-only permissions and job timeouts, and takes Python from `.python-version` | workflows; planned: actionlint |
| P5 | Production installs runtime dependencies only (`requirements-dev.txt` for tools) | Makefile, workflows |
| P6 | Toolchain versions agree: Node 24+ and npm 11+ (`engines` = `.nvmrc` major, `engine-strict`), Python from `.python-version` (`make setup` via uv, CI) | `web/.npmrc`, Makefile, workflows |
| P7 | Tests that need Docker or Chromium run in CI (a parallel job), never skip silently there | planned: CI job |

### Backend architecture (B)

| ID | Rule | Enforced by |
|----|------|-------------|
| B1 | Imports only point down the [layer order](#layers); `db` and `agent` never import `api` | import-linter (`pyproject.toml`; known violations in `ignore_imports`) |
| B2 | No importing another module's `_private` names - make it public or move it | planned: test |
| B3 | Routes stay thin: validation, one call into a helper/agent/db, response. No HTTP clients in routes | import-linter (HTTP clients); ruff `PLR0915`; judgment for thinness |
| B4 | One input mechanism: bodies via `@validate_request`, query strings via a schema too - never raw `request.args`/`get_json` in routes | planned: test |
| B5 | Errors follow [Errors](#errors) | ruff `BLE`, `TRY400`, `N818` (baselined) |
| B6 | Typing follows [Typing](#typing) | mypy strict; planned: `Any` ratchet |
| B7 | Module-level mutable state is per-worker: comment `# per-worker: <why safe>` or move it to the DB/`kv_store` ([Multi-worker state](#multi-worker-state)); constant collections are immutable | planned: test |
| B8 | An agent tool is registered in one place (registry entry: tool, availability, exclusions, display metadata) | planned: registry + completeness test; today follow the [checklist](features/agent-tools.md#adding-a-new-tool) |
| B9 | One HTTP client library: `httpx` | ruff `TID251` (10 files baselined in `pyproject.toml`) |
| B10 | An import inside a function says why (`# lazy: <reason>`) | judgment; planned: ruff `PLC0415` once the ~1,000 existing ones are sorted |
| B11 | Env vars are read only in `src/config.py`; time and size settings carry their unit (`_SECONDS`, `_MS`, `_BYTES`); true constants live in `constants.py` | judgment; planned: test |

### Frontend architecture (F)

| ID | Rule | Enforced by |
|----|------|-------------|
| F1 | Imports only point down the [layer order](#layers); no new import cycles | ESLint `no-restricted-imports` zones (baselined); planned: cycle allow-list that only shrinks |
| F2 | Store state changes only through slice actions; re-read `getState()` after any `await`; module-level `let` only for UI-ephemeral handles (timers, observers) | planned: ESLint + counter |
| F3 | Every value interpolated into HTML is escaped (`escapeHtml`) or already-safe HTML; no inline `on*=` handlers; listeners on `document`/`window` take an `AbortSignal` | planned: scan with baseline |
| F4 | No floating promises (`void` marks a deliberate one) or async callbacks where a sync one is expected; no non-null `!` | typescript-eslint (type-aware; baselined in `eslint-suppressions.json`) |
| F5 | `tsconfig` gets stricter in stages: `noImplicitReturns`, `noImplicitOverride`, `verbatimModuleSyntax` (on); `exactOptionalPropertyTypes`, `noUncheckedIndexedAccess` next | tsc; planned: stage 2 |
| F6 | API types come from `generated-api.ts` (aliases, extended for frontend-only fields), not hand-written copies | planned: compile-time compatibility test |
| F7 | CSS uses tokens from `variables.css`: no hex/`rgb()` elsewhere, z-index via tokens; one stylesheet per component prefix | planned: grep test (like `css-class-collisions.test.ts`) |
| F8 | No `console.*` outside the logger; a logger's name is its module path | ESLint `no-console`; judgment for names |
| F9 | Real `<button type="button">`, not `role="button"` on a div; an `aria-modal` dialog traps focus | planned: test |
| F10 | No unused exports (a config value nobody reads drifts from the copy someone does) | planned: knip |
| F11 | State management is Zustand ([store.ts](../web/src/state/store.ts)); dynamic content uses event delegation; `textContent` for plain text; icons from `icons.ts` | judgment |

### Code shape, both stacks (C)

| ID | Rule | Enforced by |
|----|------|-------------|
| C1 | Functions under 50 lines (100 max), nesting at most 3, bounded complexity - see [Size and structure](#size-and-structure) | ruff `C901` (complexity 10), `PLR0912`, `PLR0915`; ESLint `max-lines-per-function` (100), `max-depth` (3), `complexity` (15) - all baselined |
| C2 | No dead code or unused dependencies | planned: vulture, knip, deptry |
| C3 | Lint rule sets: ruff `E W F I B C4 UP S BLE TRY400 G LOG T20 RUF SIM RET PERF N PGH TID C90` (`RUF100` flags dead `noqa`s). Not adopted: `DTZ` (local naive datetimes are deliberate - changing them is a behavior change), `PT` and `PLC0415` (later) | ruff; existing violations carry `# noqa: CODE` |
| C4 | Formatting: ruff format (Python), ESLint (TS), Prettier (CSS, YAML, JSON; not Markdown); `.editorconfig` | ruff, ESLint, Prettier `format:check` in `make lint`; the PostToolUse hook formats on edit |
| C5 | Type hints everywhere (mypy strict), TypeScript strict | mypy, tsc |
| C6 | No backward-compatibility re-exports when moving code; update the imports | judgment |

### Testing (T)

Details: [testing.md](testing.md).

| ID | Rule | Enforced by |
|----|------|-------------|
| T1 | Bug fixes are test-first: a failing test, then the fix, then the full suite | judgment (`/fix-bug`) |
| T2 | Coverage floors follow actual coverage, about two points under it (backend 83%; frontend lines 44%, branches 40%) | `fail_under` (pyproject), vitest `coverage.thresholds` |
| T3 | No placeholder tests (a body of only `pass`, a docstring or comments) | test (`test_test_hygiene.py`) |
| T4 | No new fixed sleeps (`time.sleep`, `waitForTimeout`) without a same-line comment saying why | test (`test_test_hygiene.py`, counted: 74 and 290) |
| T5 | E2E mock responses validate against the API schema | planned |
| T6 | A flaky test fails CI unless it is on the quarantine list (with a TODO entry) | planned: post-step over the Playwright report |
| T7 | Tests exercise public behavior, not `_private` names or test-only exports | test (`test_test_hygiene.py`, counted: 92 imports) |
| T8 | A new route module or `core/*.ts` module ships with a test | planned: CI script |
| T9 | Unit tests touch neither a database nor the Flask client; anything that does is an integration test | judgment |
| T10 | E2E runs the last `make build`; rebuild after any frontend change ([rule](../.claude/rules/testing.md)) | judgment |
| T11 | UI changes are checked on desktop and mobile (768px breakpoint) | judgment; visual tests |

### Agent workflow (A)

| ID | Rule | Enforced by |
|----|------|-------------|
| A1 | Parallel sessions: stage, restore and discard explicit paths only ([AGENTS.md](../AGENTS.md#parallel-sessions)) | hook (`guard-git.py`) |
| A2 | Conventional Commits: `type(scope): description` | hook (`guard-git.py`) |
| A3 | Lint and the full suite pass in-session before a commit; exit codes are checked directly, never through a pipe | judgment |
| A4 | Generated files are regenerated, never edited (`make openapi`, `make types`) | hook (`block-generated.sh`); planned: P1 |
| A5 | Docs: a new pattern or pitfall goes into the relevant `docs/` page; numbers in docs carry a date; a shipped feature's plan and spec are deleted | link test; judgment |
| A6 | TODO items are at most two lines; a finished item is deleted in the commit that finishes it | judgment |

## Layers

Imports point down only. A lower layer that needs something from a higher one
gets it passed in (callback, parameter, event), never imported.

**Backend:** `api/routes` → `api/helpers` → `agent` → `db` → `utils`, `config`,
`constants`. `auth` sits beside `api` and may use `db`. Shared enums used by
both `db` and `api` belong in the lowest layer that needs them, not in
`api/schemas`.

**Frontend:** `main.ts` → `core` → `components` → `state` → `api` → `utils` →
`types`. `sync` sits beside `core`. Components report user actions upward
through callbacks or `core/events`, not by importing `core`; `utils` and
`sync` never import UI (`Toast` included).

## Errors

- Catch the most specific exception the call can raise. A broad
  `except Exception` needs a reason (`# noqa: BLE001 - <why>`) and logs with
  `exc_info=True` - or re-raises.
- API errors go through `raise_*_error()` from `src/api/errors.py`. Never
  return `str(e)` to a client, and never return HTTP 200 with an `error`
  field.
- Agent tools report failures through one shape (a single helper), so the
  model always sees the same structure.
- Project exceptions end in `Error`.

## Logging and privacy

Logs exist to diagnose production and to improve the agent - deep research,
the grounding verifier, tool choice - so they may carry what that needs, but
never a family member's conversation in full.

- **Identify users by `user_id`**, never by email or name.
- **Allowed, truncated** (about 200 characters): search queries, research
  questions and sub-questions, tool arguments, short prompt or claim excerpts
  that explain a decision (why the verifier flagged a claim, what a research
  step looked for).
- **Never:** full message texts or conversation histories, attachments,
  tokens, passwords, API keys.
- Structured fields via `extra={...}`, not f-strings in the message.
- Use `get_logger(__name__)` (backend) and `createLogger('<module path>')`
  (frontend); no `print` or `console.*` outside the logger.

## Typing

- mypy strict and TypeScript strict, everywhere. `# type: ignore[code]` and
  `cast` need a reason in a comment.
- A public function's dict-shaped parameter or result gets a `TypedDict`,
  dataclass or Pydantic model, not `dict[str, Any]`; the existing `Any` count
  (about 1,000, Oct 2026) may only go down.
- Frontend: no `any`, no `as unknown as`; check DOM lookups with
  `instanceof` instead of casting; parse untrusted JSON through a guard, not
  `JSON.parse(...) as T`.

## Size and structure

The limits that matter are on **functions**, not files. Bugs here cluster in
long functions and closures that hold several concerns (Oct 2026: the most
bug-prone file was 553 lines, with one 251-line closure; a 1,015-line file
went untouched for 90 days) - not in long files.

**Functions** (hard limits):
- Under 50 lines is the target, 100 the maximum.
- Nesting at most 3 levels (if/for/try/callback).
- A function longer than that is doing several things: extract them into
  named helpers (see the refactoring patterns below).

**Files** (a prompt to split, not a limit):
- Split by responsibility, not by line count. A file that mixes concerns,
  needs section comments to stay navigable, or carries a name that no longer
  describes most of it should be split at any size.
- Around **800 lines**, check whether it still has one purpose. If it does
  (declarative config, icon data, a cohesive state machine), leave it.
- Split by feature/responsibility, not by type (`conversation.ts`,
  `messaging.ts` - not `handlers.ts`, `utils.ts`).

Why it still matters with capable models, which read large files fine:
- **Context cost**: an agent reading a 1,400-line file pays ~15-20k tokens
  each time, and when it reads only part of it, it misses what is defined
  elsewhere in the file.
- **Edit precision**: edits match exact text; long files repeat more
  patterns, so edits land ambiguously or fail.
- **Parallel sessions**: several agents work in one checkout. A file every
  feature touches (`core/init.ts`) is a merge-conflict point at any size -
  give each feature its own module and a one-line hook-up.

### When to split
- A function exceeds the limits above.
- The file has several unrelated responsibilities, or its name no longer fits.
- Most changes to the file touch different, unrelated parts of it.
- Testing one part requires setting up the others.

### How to split
Use `/split-file`. In short: group by responsibility, move code into focused
modules (a subdirectory when there are several), update every import (no
re-exports), and run lint and the full suite.

### Refactoring patterns
Extract a helper when you see deep nesting, repeated logic, code that is hard
to test alone, or a conditional that deserves a name.
- **State encapsulation**: group related variables into a class/interface (e.g., `_StreamContext`, `StreamingState`)
- **Handler extraction**: move event handlers to separate named functions
- **Parser helpers**: extract parsing/validation logic into reusable functions
- **Choreography helpers**: extract complex async/callback sequences into named functions

## Multi-worker state

Production runs multiple gunicorn workers (count set by `GUNICORN_WORKERS`, default 2 - verify against `src/config.py` rather than assuming a fixed number). Each worker is a separate process, so **module-level dicts and globals are per-worker and NOT shared**: state written in one HTTP request may land in a different worker on the next request and be invisible.

- Any multi-step or stateful flow that can span requests (e.g. multi-step OAuth / MFA like Garmin's) must be **stateless on the backend** or persist to a **shared store** (the database or `kv_store`). If step 2 needs data from step 1, have the client resend it rather than relying on in-process state.
- A shared / cross-worker store cannot hold **live library objects** - anything with thread locks, network sessions, or sockets (e.g. a partially-authenticated `garminconnect.Garmin` client) is not picklable and will raise `TypeError: cannot pickle '_thread.RLock' object`. `kv_store` (pickle + base64) works only for serializable data - dicts, tokens, strings.
- Flask's `test_client` is single-process and never reproduces cross-worker breakage. If a flow's correctness depends on within-process state, write a test that asserts the contract is stateless (or document the requirement explicitly).
