---
paths:
  - "src/api/routes/sports.py"
  - "src/api/routes/language.py"
  - "src/db/models/sports.py"
  - "src/db/models/language.py"
  - "web/src/core/sports.ts"
  - "web/src/core/language.ts"
  - "web/src/components/*Dashboard.ts"
---

# Program-based features (Sports, Language)

Sports and Language share the same architecture: each "program" is a dedicated conversation (`is_sports`/`is_language` flag + program slug) with a specialized system prompt and `kv_store` persistence. The pattern:

- **Backend**: `routes/{feature}.py` (5 CRUD+reset endpoints), `models/{feature}.py` (DB mixin), `prompts.py` (system prompt + KV formatting)
- **Frontend**: `core/{feature}.ts` (navigation + CRUD), `components/{Feature}Dashboard.ts` (UI + modal), `styles/components/{feature}.css`
- **Quick actions**: per-program saved prompts stored INSIDE the program object (`programs` KV list, never under `{program_id}:*`), shared route in `routes/program_quick_actions.py`; see [docs/features/ui-features.md](../../docs/features/ui-features.md#program-quick-actions).
- **Language-specific**: `QuizBlock.ts` renders interactive quizzes from ` ```quiz ` fenced code blocks (MC, fill-blank, translate, batch types). All evaluation is done by the LLM — the client only collects and sends answers.

See [docs/features/language-learning.md](../../docs/features/language-learning.md) for detailed language feature docs.
