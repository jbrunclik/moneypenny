---
description: Update dependencies safely - Python lock, npm, Dependabot, audit
---

Update dependencies: $ARGUMENTS

**Python**
- Runtime ranges live in `requirements.in`, tools (ruff, mypy, pytest...) in
  `requirements-dev.in`; the `.txt` files are the generated locks. Edit a range,
  then `make lock` (never hand-edit a lock). Production installs only
  `requirements.txt`, so a runtime package must not land in the dev file.
- `make setup` installs it; run `make lint` and `make test`.

**npm** (`web/`)
- `npm install <pkg>@<version>`, commit `package.json` and `package-lock.json`
  together. Never `npm audit fix --force` - it jumps majors (it once pulled an
  incompatible openapi-typescript).
- `@playwright/test` is pinned exactly: a bump changes the CI container image
  and usually every visual baseline (`/regen-baselines`). Check
  `docs/testing/e2e-reliability.md` for known version issues first.
- TypeScript stays below 7 until typescript-eslint supports it (TODO.md).

**Dependabot**
- Patch and minor PRs auto-merge after CI passes; majors need a person.
- Bot merges don't trigger the Tests workflow on `main`: dispatch it manually
  when a batch lands.

**Verify**: `make audit` (pip-audit + npm audit), `make lint`, `make test-all`;
for a runtime dependency, a quick `make dev` smoke test of the affected
feature.
