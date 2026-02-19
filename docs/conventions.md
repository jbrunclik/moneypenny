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
