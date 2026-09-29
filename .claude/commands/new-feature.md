---
description: Feature workflow - superpowers brainstorming + TDD, then review/docs
---

Implement a new feature: $ARGUMENTS

The superpowers process skills are the backbone now — this command wires them
to the project's conventions.

1. **Design first (gated).** Invoke the `superpowers:brainstorming` skill BEFORE
   writing any code. It classifies the work (spike / bounded / architectural)
   and stops for your approval. Don't skip to code.

2. **Implement with TDD.** Invoke `superpowers:test-driven-development`. Follow
   existing patterns; functions <50 lines; type hints (Python) / strict TS;
   pull magic values from `config.{ts,py}` and `constants.{ts,py}`.

3. **Test.** Backend unit → `tests/unit/`, integration → `tests/integration/`,
   UI → `web/tests/e2e/`. E2E runs the last `make build`, so rebuild before
   Playwright. Visual change? see `/regen-baselines`.

4. **Review.** After significant changes, invoke `superpowers:requesting-code-review`.

5. **Docs.** Run the `docs-updater` agent. Keep infra details (hostnames,
   server topology) OUT of repo docs — that knowledge lives in private memory.

6. **Finish.** `superpowers:verification-before-completion`, then
   `make pre-commit` (lint + all tests; rebuilds before E2E) — check its exit
   code. Skip it only if lint + the full suite already passed in-session.
