---
paths:
  - "migrations/**"
---

# Database migrations

- `make migration NAME=add_foo` scaffolds the next `migrations/NNNN_add_foo.py` (yoyo).
- Set `__depends__ = {"<previous migration id>"}` and give every step a rollback. SQLite here supports `ALTER TABLE ... DROP COLUMN`.
- Migrations apply automatically when the app starts (`Database._init_db`), locally and on deploy. A reload mid-migration can strand a half-applied step, so never deploy twice in quick succession.
- Never drop a scratch or probe file into `migrations/`, even for a minute: a running dev server or E2E server applies it to its database at once (Oct 25 2026: a test probe landed in the local `chatbot.db`). Test migration logic against a temp copy of the directory.
- See [docs/architecture/database.md](../../docs/architecture/database.md).
