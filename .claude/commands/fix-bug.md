---
description: TDD bug fix workflow - reproduce, test, fix, verify
---

Fix a bug using the TDD approach. The bug to fix: $ARGUMENTS

Follow this workflow strictly:

1. **Understand the bug**: Read the relevant code to understand the root cause. If the user provided a description, analyze it. If not, ask for details.

2. **Write a failing test**: Create a test that reproduces the bug.
   - Unit test in `tests/unit/` for backend logic bugs
   - Integration test in `tests/integration/` for API bugs
   - E2E test in `web/tests/e2e/` for UI bugs
   - Follow patterns in `tests/conftest.py` for fixtures and mocks

3. **Run the test**: Confirm it fails with the expected error.
   ```bash
   make test  # or specific test file
   ```

4. **Implement the fix**: Make the minimal change needed.

5. **Run the test again**: Confirm it passes.

6. **Run the full test suite**: Ensure no regressions.
   ```bash
   make test-all
   ```

7. **Code review**: Use the `code-reviewer` agent to review your fix.

8. **Pre-commit check**: Use the `pre-commit` agent to verify everything passes.
