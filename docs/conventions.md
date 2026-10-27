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
  baseline is a bare `# noqa: CODE` on the line (Oct 25 2026: 407; none left since Oct 26 2026); a
  deliberate exception carries a reason instead: `# noqa: CODE - <why>`.
  For ESLint it is `web/eslint-suppressions.json` (228): after fixing some,
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
| S5 | Every outbound call has an explicit timeout, LLM clients included (Gemini: `GEMINI_REQUEST_TIMEOUT_SECONDS`, per read) | test (`test_outbound_timeouts.py`) |
| S6 | Model output never loads external resources by itself (external markdown images render as links; CSP `img-src` allows only the app and Google profile photos) | test (`markdown.test.ts`, `test_security_headers.py`) |
| S7 | Production requires a valid `TOKEN_ENCRYPTION_KEY` | test (`test_config.py`) |
| S8 | Logging follows the [privacy policy below](#logging-and-privacy) | test (`test_log_fields.py`, and `web/tests/unit/log-fields.test.ts` for client logs: no email, credential or whole-text fields); judgment for truncation |
| S9 | No secrets or infrastructure details in tracked files or commit messages (the repo is public) | CI (gitleaks + a `FORBIDDEN_PATTERNS` secret scan); gitleaks on commit locally |
| S10 | Public API docs (`/api/docs`, `/api/openapi.json`) are off in production | test (`test_security_headers.py`) |
| S11 | Deploys can't overlap and can be rolled back (lock, previous SHA, backup before migrations, assets swapped without a gap) | `make update` / `make rollback` ([deployment.md](deployment.md#deploying-and-rolling-back)) |
| S12 | Spend of more than $10 per user per day shows that user a banner (something looks off) - never a block, no notification; the admin sees total spend in the app ([admin.md](features/admin.md)) | tests (`test_routes_admin.py`, `spend-banner.test.ts`, `admin.spec.ts`) |

### Delivery (P)

| ID | Rule | Enforced by |
|----|------|-------------|
| P1 | Generated files never drift: `static/openapi.json` and `generated-api.ts` match the schemas, `requirements.txt` matches `requirements.in`, `.env.example` lists every config variable | CI (regenerate and diff); test (`test_env_example.py`) |
| P2 | Migrations form one chain with unique numbers; each step has a rollback or an `# irreversible:` reason | test (`test_migration_chain.py`) |
| P3 | Dependabot auto-merges patch and minor updates only, after Tests and (when a lock file changed) the Dependency Audit passed | workflow + tests (`test_dependabot_majors.py`, `test_dependabot_run_gate.py`) |
| P4 | CI cancels superseded runs, has read-only permissions and job timeouts, and takes Python from `.python-version` | workflows; actionlint in CI |
| P5 | Production installs runtime dependencies only (`requirements-dev.txt` for tools) | Makefile, workflows |
| P6 | Toolchain versions agree: Node 24+ and npm 11+ (`engines` = `.nvmrc` major, `engine-strict`), Python from `.python-version` (`make setup` via uv, CI) | `web/.npmrc`, Makefile, workflows |
| P7 | Tests that need Docker or Chromium run in CI (a parallel job), never skip silently there | CI job "Backend Docker & Browser Tests" (no skips allowed) |

### Backend architecture (B)

| ID | Rule | Enforced by |
|----|------|-------------|
| B1 | Imports only point down the [layer order](#layers); `db` and `agent` never import `api`, `db` never imports `services`, `utils` imports no other layer | import-linter (`pyproject.toml`; no baseline) |
| B2 | No importing another module's `_private` names - make it public or move it | `tests/unit/test_private_imports.py` (`src/`; only APIFlask's `_annotate` baselined, Oct 26 2026); T7 for tests |
| B3 | Routes stay thin: validation, one call into a helper/agent/db, response. No HTTP clients in routes | import-linter (HTTP clients); ruff `PLR0915`; judgment for thinness |
| B4 | One input mechanism: bodies via `@validate_request`, query strings via a schema too - never raw `request.args`/`get_json` in routes | `tests/unit/test_route_input.py` |
| B5 | Errors follow [Errors](#errors) | ruff `BLE`, `TRY400`, `N818` (baselined); `tests/unit/test_tool_errors.py` (no `"Error: ..."` tool results) |
| B6 | Typing follows [Typing](#typing) | mypy strict; `tests/unit/test_any_ratchet.py` (`Any` uses in `src/` only go down: 1,140 on Oct 26 2026, 1,068 on Oct 27 once file attachments (`StoredFile`, `UploadedFile` in `src/utils/files.py`) and the message payloads (`ClaimAnnotation`, `GroundingSummary`, `MessageAction`, `ArtifactShown` in `src/db/models/dataclasses.py`) were typed) |
| B7 | Module-level mutable state is per-worker: comment `# per-worker: <why safe>` or move it to the DB/`kv_store` ([Multi-worker state](#multi-worker-state)); a lazy singleton is a `Lazy` (`src/utils/lazy.py`), not another hand-written double-checked lock; constant collections are immutable | `tests/unit/test_per_worker_state.py` (the comment); judgment (immutable constants) |
| B8 | An agent tool is registered in one place (registry entry: tool, availability, exclusions, display metadata) | planned: registry + completeness test; today follow the [checklist](features/agent-tools.md#adding-a-new-tool) |
| B9 | One HTTP client library: `httpx` | ruff `TID251` |
| B10 | An import inside a function says why: `# noqa: PLC0415 - <reason>` (a cycle, a heavy optional dependency) | ruff `PLC0415` in `src/` (none baselined) |
| B11 | Env vars are read only in `src/config.py`; time and size settings carry their unit (`_SECONDS`, `_MS`, `_BYTES`); true constants live in `constants.py` | `tests/unit/test_config_reads.py` (env reads outside `config.py`; duration and byte-size `Config` names without a unit, 20 baselined Oct 26 2026 - each is set in the real `.env` files, so a rename lands there in the same deploy); judgment (constants) |
| B12 | Datetimes are aware: instants are UTC (`src/utils/clock.py`: `utc_now`, `to_api` for the API, `to_local` for display and prompts), the household's days and months are drawn in `APP_TIMEZONE` (`local_today`, `local_day_start`, `planner_cutoff`, the SQL `app_local_date`), stored values go through `timestamps.from_db` / `to_db` ([Timestamps](architecture/database.md#timestamps)); the API sends every instant as `YYYY-MM-DDTHH:MM:SS.ffffff+00:00` | ruff `DTZ` (src, scripts, evals; no baseline); `tests/unit/test_naive_datetimes.py` (naive parsing, host-zone conversion, `replace(tzinfo=None)`; a deliberate one says `# tz-naive: <why>`); `tests/integration/test_api_timestamps.py` (spec `format: date-time` and live responses); `make test-tz` (the suite under two far-off process timezones) |

### Frontend architecture (F)

| ID | Rule | Enforced by |
|----|------|-------------|
| F1 | Imports only point down the [layer order](#layers); no new import cycles | ESLint `no-restricted-imports` zones (baselined); `web/tests/unit/import-cycles.test.ts` (runtime import edges inside a cycle; `import-cycles.baseline.json` only shrinks - empty since Oct 26 2026) |
| F2 | Store state changes only through slice actions; re-read `getState()` after any `await`; module-level `let` only for UI-ephemeral state: a handle, or module-local UI state marked in place with `// UI-local (F2): <why>` | ESLint `local/no-stale-store-snapshot` (`web/eslint-rules/`: a state field read from a `useStore.getState()` snapshot after an `await` or in a `.then` callback; calls are actions and pass; heuristic and gaps in the rule file); `web/tests/unit/module-state.test.ts` (fails on a module-level `let` that is neither typed as a handle - timer, observer, AbortController, element, function, promise - nor marked; one marker covers the `let`s right after it; no baseline since Oct 26 2026, when the settings data moved to the store and the rest were marked) |
| F3 | The DOM is built with elements (`createElement`, `createSvgElement`, `setIcon`/`createIconButton` for static icons); the only computed HTML write is `setSanitizedHtml` (`web/src/utils/dom.ts`), which takes a `SanitizedHtml` - minted only by the sanitizers (`renderMarkdown`, `highlightCode`/`highlightLanguage`, mermaid's DOMPurify'd SVG); a server- or agent-provided URL goes into an `href` only through `safeHttpUrl` (`web/src/utils/linkify.ts`; escaping alone leaves `javascript:` clickable); no inline `on*=` handlers; listeners on `document`/`window` take an `AbortSignal` | ESLint `no-unsanitized` (trusts only `setSanitizedHtml`'s unwrap, `SAFE_HTML` in `web/eslint.config.js`; none baselined); the `SanitizedHtml` type (`web/tests/unit/sanitized-html.test.ts`); planned: `on*=` and listener checks |
| F4 | No floating promises (`void` marks a deliberate one) or async callbacks where a sync one is expected; no non-null `!` | typescript-eslint (type-aware; baselined in `eslint-suppressions.json`) |
| F5 | `tsconfig` is strict beyond `strict`: `noImplicitReturns`, `noImplicitOverride`, `verbatimModuleSyntax`, `noUncheckedIndexedAccess` (narrow an indexed value with a guard, `for...of` or `?.`, never `!`) and `exactOptionalPropertyTypes` (leave out an optional key that has no value - `...(x !== undefined && { key: x })` - rather than set it to `undefined`; write `key?: T \| undefined` only where `undefined` is a real value: a patch that clears a field through a `{...a, ...b}` merge, or mutable state reset in place) | tsc |
| F6 | API types come from `generated-api.ts` (aliases, extended for frontend-only fields), not hand-written copies. The spec tells requests from responses: schemas inherit `RequestModel` (defaulted fields optional) or `ResponseModel` (every field sent), and `make types` follows `required` only (`--default-non-nullable false`) | `tests/integration/test_schema_directions.py` (every schema picks a direction; a response nests no request model), `web/tests/unit/api-types.test.ts` (a hand-written `src/` object type sharing most property names with a generated schema is a copy; `api-types.baseline.json` only shrinks) |
| F7 | CSS uses tokens from `variables.css`: no hex/`rgb()` elsewhere, z-index via tokens; a class's own rules (`.x`, `.x:hover`, `.x.active` - not context rules like `.header .x`) live in one stylesheet | `web/tests/unit/css-tokens.test.ts` (z-index above 10 needs a `--z-*` token; layout.css, glass.css and mobile-sheets.css are cross-component layers; no baseline: colours and z-indexes went to 0 on Oct 26 2026, as exact-value tokens - the fixed palette in variables.css for what never followed the theme - and spread classes on Oct 27, when the first-word prefix check (42 pairs, mostly unrelated components sharing a word) gave way to this one and its 8 real cases were fixed; it replaced the css-class-collisions allowlist test) |
| F8 | No `console.*` outside the logger; a logger's name is its module path | ESLint `no-console`; judgment for names |
| F9 | Real `<button>`, not `role="button"` on a div - except a row that holds other buttons (a `<button>` cannot nest them), which keeps `role="button"` with `tabindex` and Enter/Space handling; a button inside a `<form>` declares its `type`; an `aria-modal` dialog traps focus | `web/tests/unit/button-types.test.ts` (types in forms); judgment (the rest; every `aria-modal` dialog traps focus and every `role="button"` handles Enter/Space as of Oct 25 2026) |
| F10 | No unused exports (a config value nobody reads drifts from the copy someone does) | knip (`web/knip.jsonc`, in `make lint`; no baseline - a deliberate alias export carries `@alias`) |
| F11 | State management is Zustand ([store.ts](../web/src/state/store.ts)); dynamic content uses event delegation; `textContent` for plain text; icons from `icons.ts` | judgment |
| F12 | A list the sync change log keeps current (archive, trash, any new one) is loaded at startup only after the first full sync has its cursor - [sync](features/sync.md#9-lists-loaded-at-startup-oct-27-2026) | `web/tests/unit/startup-initial-data.test.ts` (the lists load in `startSync`'s `onStarted`); judgment for a new list |

### Code shape, both stacks (C)

| ID | Rule | Enforced by |
|----|------|-------------|
| C1 | Functions under 50 lines (100 max), nesting at most 3, bounded complexity - see [Size and structure](#size-and-structure) | ruff `C901` (complexity 10), `PLR0912`, `PLR0915`; `tests/unit/test_function_length.py` (Python 100-line maximum, docstrings excluded; baseline only shrinks); ESLint `max-lines-per-function` (100), `max-depth` (3), `complexity` (15) - the ESLint ones baselined |
| C2 | No dead code or unused dependencies | knip (frontend files, exports, npm deps; no baseline); vulture (`src/`, `evals/`, `scripts/`, the E2E server; config in `pyproject.toml`, what it can't see in `vulture_whitelist.py` with reasons; no baseline); deptry (`deptry.toml`: imports vs `requirements.in` / `requirements-dev.in`) |
| C3 | Lint rule sets: ruff `E W F I B C4 UP S BLE TRY400 G LOG T20 RUF SIM RET PERF N PGH TID C90 DTZ` (`RUF100` flags dead `noqa`s). `PLC0415` in `src/`. `DTZ` (B12) outside `tests/`. Not yet: `PT` | ruff; a deliberate exception carries `# noqa: CODE - <why>` |
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
| T4 | No new fixed sleeps (`time.sleep`, `waitForTimeout`) without a same-line comment saying why; after navigating, an E2E spec waits for `appReady(page)` (startup settled), not a shell element that exists from the first paint | test (`test_test_hygiene.py`, both at 0: `waitForTimeout` since Oct 26 2026, `time.sleep` since Oct 27 - rows written back to back get distinct timestamps from the test clock (`strictly_increasing_clock` in `tests/conftest.py`), a chat turn's threads are joined with the `join_turn_threads` fixture, and in E2E wait on a condition with `web/tests/e2e/waits.ts` (`appReady`, `nextFrames`, `scrollSettled`, `pageSettled`, `serverReplySaved`) or an auto-waiting assertion; a fixed span stays only where elapsed time is the subject; `waitForSelector` on `#app`, `#new-chat-btn`, `#user-info`, `#menu-btn` or `#sidebar` is refused, at 0 since Oct 27) |
| T5 | E2E mock responses validate against the API schema | test (`test_e2e_mock_schema.py`) |
| T6 | A flaky test fails CI unless it is on the quarantine list (with a TODO entry) | `web/tests/flaky-gate.ts` after each CI E2E shard (reads the JSON report; `web/tests/e2e/flaky-quarantine.json` lists the allowed flakes, `tests/unit/flaky-gate.test.ts` checks each entry names a real test) |
| T7 | Tests exercise public behavior, not `_private` names or test-only exports | test (`test_test_hygiene.py`: no import of a `_private` name from `src`; the 66 of Oct 26 2026 went the same day - pure logic moved to modules with public names, the rest tested through its entry point) |
| T8 | A new route module or `core/*.ts` module ships with a test | `tests/unit/test_route_tests.py` (`tests/integration/test_routes_<name>.py` or an integration test importing it; the 7 baselined moved to their own files Oct 26 2026, so the baseline is empty), `web/tests/unit/core-tests.test.ts` (imported at runtime by a unit or component test - `vi.mock` alone doesn't count; the 12 baselined got tests the same day, so the baseline is empty), Oct 26 2026; both baselines only shrink |
| T9 | Unit tests touch neither a database nor the Flask client; anything that does is an integration test | judgment |
| T10 | E2E runs the last `make build`; rebuild after any frontend change ([rule](../.claude/rules/testing.md)) | judgment |
| T11 | UI changes are checked on desktop and mobile (768px breakpoint) | judgment; visual tests |
| T12 | A guard test (a scan or contract that enforces a rule) also proves it can fail: a built-in case with the banned pattern, or a mutation checked once by hand and named in the commit | judgment; examples `test_naive_datetimes.py` (`test_the_scan_sees_each_pattern`), `test_payload_parity.py` (`test_the_check_sees_a_drift`) |

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

**Backend:** `api/routes` → `api/helpers` → `agent` → `services` → `db` →
`utils`, `config`, `constants`. `services` holds the modules that need the
database (costs, push, file retention, thumbnails, search quotas); `utils` is
pure and imports nothing else from `src` except `config`, `constants` and
`enums`. `auth` sits beside `api` and may use `db`. Shared enums used by
both `db` and `api` belong in the lowest layer that needs them
(`src/enums.py`), not in `api/schemas`.

**Frontend:** `main.ts` → `core` → `components` → `state` → `api` → `utils` →
`types`. `sync` sits beside `core`. Components report user actions upward
through callbacks or `core/events`, not by importing `core`; `utils` and
`sync` never import UI (`Toast` included). A component, `utils` or `sync`
module that needs something from above gets it from a `core/startup/*`
module before the session starts (`initClaimCard({ send })`,
`setPushControls`, `setQuizRenderer`, the `initSyncManager` notifier) or as
an argument (`openPdfViewer`'s `onDownload`). Inside `core`, the feature views
(agents, sports) sit above conversation selection and switching: they open
conversations and send, so `conversation.ts` and `conversation-switch.ts`
reach them only through hooks `core/startup/navigation.ts` sets before anything
can navigate (`setViewLeavers`, `setAgentHeaderActions`); an unset hook logs at
debug and does nothing. Add a new view's leaver there.

## Errors

- Catch the most specific exception the call can raise. A broad
  `except Exception` needs a reason (`# noqa: BLE001 - <why>`) and logs with
  `exc_info=True` - or re-raises. Ruff stops flagging a broad except once it
  logs with `exc_info=True` or `logger.exception()`, and RUF100 then rejects
  the noqa, so such an except gets a plain `# <why>` comment; keep
  `# noqa: BLE001 - <why>` only where ruff still flags the line.
- API errors go through `raise_*_error()` from `src/api/errors.py`. Never
  return `str(e)` to a client, and never return HTTP 200 with an `error`
  field.
- Agent tools report failures through `tool_error()`
  (`src/agent/tools/errors.py`): a JSON `{"error": ...}` envelope the graph's
  self-correction recognises; `retriable=False` when a retry cannot help.
  A dispatcher whose action handlers return dicts (Todoist, Google Calendar)
  serializes them with `action_result()`, which sends one with an `"error"`
  key out through `tool_error()`.
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
  (1,068, Oct 27 2026) may only go down. A file attachment is an
  `UploadedFile` while a turn carries its bytes and a `StoredFile` as
  `messages.files` keeps it (`src/utils/files.py`).
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
  feature touches is a merge-conflict point at any size - give each feature
  its own module and a one-line hook-up (as `core/init.ts` does with
  `core/startup/`).

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
- **State encapsulation**: group related variables into a class/interface (e.g., `StreamContext`, `StreamingState`)
- **Handler extraction**: move event handlers to separate named functions
- **Parser helpers**: extract parsing/validation logic into reusable functions
- **Choreography helpers**: extract complex async/callback sequences into named functions

## Multi-worker state

Production runs multiple gunicorn workers (count set by `GUNICORN_WORKERS`, default 2 - verify against `src/config.py` rather than assuming a fixed number). Each worker is a separate process, so **module-level dicts and globals are per-worker and NOT shared**: state written in one HTTP request may land in a different worker on the next request and be invisible.

- Any multi-step or stateful flow that can span requests (e.g. multi-step OAuth / MFA like Garmin's) must be **stateless on the backend** or persist to a **shared store** (the database or `kv_store`). If step 2 needs data from step 1, have the client resend it rather than relying on in-process state.
- A shared / cross-worker store cannot hold **live library objects** - anything with thread locks, network sessions, or sockets (e.g. a partially-authenticated `garminconnect.Garmin` client) is not picklable and will raise `TypeError: cannot pickle '_thread.RLock' object`. `kv_store` (pickle + base64) works only for serializable data - dicts, tokens, strings.
- Every module-level container, `Lazy` singleton or `global`-rebound name carries `# per-worker: <why safe>` on its line or in the comment block above (`tests/unit/test_per_worker_state.py` fails otherwise). Safe reasons: a cache rebuilt on a miss, state keyed by a request that runs in one worker, a resource owned by the process (threads, browser sessions, containers). Anything another request must see goes to the database or `kv_store`.
- Flask's `test_client` is single-process and never reproduces cross-worker breakage. If a flow's correctness depends on within-process state, write a test that asserts the contract is stateless (or document the requirement explicitly).
