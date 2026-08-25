---
description: Bug-fix workflow - systematic-debugging + TDD (failing test first)
---

Fix a bug: $ARGUMENTS

1. **Root cause first (no fixes yet).** Invoke `superpowers:systematic-debugging`.
   Read the error fully, reproduce it, trace the bad value to its source. Do NOT
   propose a fix before the root cause is understood — symptom patches regress.

2. **Failing test first.** Invoke `superpowers:test-driven-development`. Write a
   test that reproduces the bug and watch it fail for the *expected* reason:
   - backend logic → `tests/unit/`
   - API behavior → `tests/integration/`
   - UI → `web/tests/e2e/` (rebuild first; E2E runs the last `make build`)

3. **Minimal fix.** Smallest change that makes the test pass. No "while I'm here."

4. **Verify.** Test passes; full suite green (`make test-all`); no new warnings.

5. **Pre-commit.** Run the `pre-commit` agent unless lint + tests already ran
   green in-session.
