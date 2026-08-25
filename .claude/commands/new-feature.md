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

4. **Review.** Run the `code-reviewer` agent after significant changes.

5. **Docs.** Run the `docs-updater` agent. Keep infra details (hostnames,
   server topology) OUT of repo docs — that knowledge lives in private memory.

6. **Finish.** `superpowers:verification-before-completion`, then the
   `pre-commit` agent (skip it only if in-session lint + tests already passed
   green).
