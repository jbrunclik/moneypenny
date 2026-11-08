---
paths:
  - "src/api/routes/sports.py"
  - "src/api/routes/language.py"
  - "src/api/routes/programs.py"
  - "src/api/routes/program_quick_actions.py"
  - "src/db/models/programs.py"
  - "web/src/core/sports.ts"
  - "web/src/core/language.ts"
  - "web/src/components/*Dashboard.ts"
---

# Program-based features (Sports, Language)

Sports and Language share the same architecture: each "program" is a dedicated conversation (`is_sports`/`is_language` flag + program slug) and `kv_store` persistence. It is a **standing chat** (as are agent chats): an ordinary chat turn with the full chat tools, plus a `# This Chat: <name>` prompt section carrying the coaching/tutor prompt and the program's KV data (`standing_for_program()` in `src/api/helpers/standing_context.py`, `format_standing_section()` in `src/agent/prompts.py`). (The per-program tool exclusions, cache profiles and contextvars were removed in Nov 2026.) The pattern:

- **Backend**: `routes/{feature}.py` (5 CRUD+reset endpoints), `models/programs.py` (shared DB mixin), `prompt_texts/{feature}.py` (coaching/tutor prompt text) + `prompt_programs.py` (KV formatting, quick-action note)
- **Frontend**: `core/{feature}.ts` (navigation + CRUD), `components/{Feature}Dashboard.ts` (UI + modal), `styles/components/{feature}.css`
- **Quick actions**: per-program saved prompts stored INSIDE the program object (`programs` KV list, never under `{program_id}:*`), shared route in `routes/program_quick_actions.py`; see [docs/features/ui-composer.md](../../docs/features/ui-composer.md#program-quick-actions).
- **Language-specific**: `QuizBlock.ts` renders interactive quizzes from ` ```quiz ` fenced code blocks (MC, fill-blank, translate, batch types). All evaluation is done by the LLM — the client only collects and sends answers.

See [docs/features/language-learning.md](../../docs/features/language-learning.md) for detailed language feature docs.
