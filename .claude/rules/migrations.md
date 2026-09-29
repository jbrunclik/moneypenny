---
paths:
  - "migrations/**"
---

# Database migrations

- `make migration NAME=add_foo` scaffolds the next `migrations/NNNN_add_foo.py` (yoyo).
- Set `__depends__ = {"<previous migration id>"}` and give every step a rollback. SQLite here supports `ALTER TABLE ... DROP COLUMN`.
- Migrations apply automatically when the app starts (`Database._init_db`), locally and on deploy. A reload mid-migration can strand a half-applied step, so never deploy twice in quick succession.
- See [docs/architecture/database.md](../../docs/architecture/database.md).
