# Code Conventions

Detailed code quality guidelines and patterns for the Moneypenny project. See [AGENTS.md](../AGENTS.md) for the summary rules.

## Code Quality Guidelines

### Extract helpers when you see:
- Deeply nested code (3+ levels of if/for/try)
- Repeated logic patterns (DRY principle)
- Code that's hard to test in isolation
- Long functions that do multiple things
- Complex conditionals that could be named

### Refactoring patterns:
- **State encapsulation**: Group related variables into a class/interface (e.g., `_StreamContext`, `StreamingState`)
- **Handler extraction**: Move event handlers to separate named functions
- **Parser helpers**: Extract parsing/validation logic into reusable functions
- **Choreography helpers**: Extract complex async/callback sequences into named functions

## Size and structure

The limits that matter are on **functions**, not files. Bugs here cluster in
long functions and closures that hold several concerns (Oct 2026: the most
bug-prone file was 553 lines, with one 251-line closure; a 1,015-line file
went untouched for 90 days) - not in long files.

**Functions** (hard limits):
- Under 50 lines is the target, 100 the maximum.
- Nesting at most 3 levels (if/for/try/callback).
- A function longer than that is doing several things: extract them into
  named helpers (see the refactoring patterns above).

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

### When to split:
- A function exceeds the limits above.
- The file has several unrelated responsibilities, or its name no longer fits.
- Most changes to the file touch different, unrelated parts of it.
- Testing one part requires setting up the others.

### How to split:
1. Identify logical groupings by feature/responsibility
2. Create new modules in a subdirectory (e.g., `core/`, `routes/`, `models/`)
3. Move code to new modules with clear exports
4. Update imports across the codebase - no backward compatibility re-exports
5. Run linting and tests to verify

### Examples of successful splits:
- `src/api/routes.py` (1500+ lines) -> `src/api/routes/` (11 focused modules)
- `src/agent/chat_agent.py` (800+ lines) -> `src/agent/` (7 focused modules)
- `src/db/models.py` (600+ lines) -> `src/db/models/` (4 focused modules)
- `web/src/main.ts` (3100+ lines) -> `web/src/core/` (11 focused modules)
- `web/src/components/Messages.ts` (1100+ lines) -> `web/src/components/messages/` (9 focused modules)

## Multi-worker state

Production runs multiple gunicorn workers (count set by `GUNICORN_WORKERS`, default 2 - verify against `src/config.py` rather than assuming a fixed number). Each worker is a separate process, so **module-level dicts and globals are per-worker and NOT shared**: state written in one HTTP request may land in a different worker on the next request and be invisible.

- Any multi-step or stateful flow that can span requests (e.g. multi-step OAuth / MFA like Garmin's) must be **stateless on the backend** or persist to a **shared store** (the database or `kv_store`). If step 2 needs data from step 1, have the client resend it rather than relying on in-process state.
- A shared / cross-worker store cannot hold **live library objects** - anything with thread locks, network sessions, or sockets (e.g. a partially-authenticated `garminconnect.Garmin` client) is not picklable and will raise `TypeError: cannot pickle '_thread.RLock' object`. `kv_store` (pickle + base64) works only for serializable data - dicts, tokens, strings.
- Flask's `test_client` is single-process and never reproduces cross-worker breakage. If a flow's correctness depends on within-process state, write a test that asserts the contract is stateless (or document the requirement explicitly).
