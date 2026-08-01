# Code Conventions

Detailed code quality guidelines and patterns for the AI Chatbot project. See [AGENTS.md](../AGENTS.md) for the summary rules.

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

## File Size Guidelines

**Keep files under 500 lines** - Large files are difficult for LLMs to process effectively:
- Files over 500 lines should be split into focused modules
- Split by feature/responsibility, not by type (e.g., `conversation.ts`, `messaging.ts`, not `handlers.ts`, `utils.ts`)
- Each module should have a single, clear purpose

### When to split a file:
- File exceeds 500 lines
- File has multiple unrelated responsibilities
- You find yourself using section comments to organize code
- Testing becomes difficult due to too many concerns

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
