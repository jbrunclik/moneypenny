---
description: Feature implementation workflow - plan, implement, test, review
---

Implement a new feature. The feature to implement: $ARGUMENTS

Follow this workflow:

1. **Plan**: Enter plan mode to explore the codebase and design the approach.
   - Search for existing patterns related to this feature
   - Identify files that need to change
   - Consider edge cases and error handling
   - Present the plan for approval

2. **Implement**: After plan approval, implement the feature.
   - Follow existing patterns in the codebase
   - Keep functions small (<50 lines)
   - Add type hints (Python) / strict TypeScript types
   - Use constants from `config.{ts,py}` and `constants.{ts,py}`

3. **Test**: Add tests for the new functionality.
   - Backend unit tests in `tests/unit/`
   - Integration tests in `tests/integration/` for new API endpoints
   - E2E tests in `web/tests/e2e/` for significant UI changes

4. **Review**: Use the `code-reviewer` agent to review the implementation.

5. **Documentation**: Use the `docs-updater` agent to update documentation.

6. **Pre-commit**: Use the `pre-commit` agent to verify everything passes.
