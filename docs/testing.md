# Testing

Moneypenny has comprehensive test coverage across both backend and frontend, including unit tests, integration tests, end-to-end tests, and visual regression tests.

## Overview

The project uses different testing strategies appropriate for each layer:

- **Backend**: pytest for unit and integration tests
- **Frontend**: Vitest for unit/component tests, Playwright for E2E tests
- **Visual**: Playwright screenshots with pixel-perfect comparison

### Test Philosophy

- **Zero tolerance for flaky tests** - All tests must pass consistently
- **Test before fixing bugs (TDD)** - Write failing test first, then fix
- **Mock external services** - Never make real API calls in tests
- **Isolated state** - Each test gets its own database/context

## Pages

| Page | Covers |
|------|--------|
| [testing/backend.md](testing/backend.md) | pytest layout, fixtures, chat-path mock return shapes, writing backend tests |
| [testing/frontend.md](testing/frontend.md) | Vitest unit/component tests, Playwright E2E, the E2E mock server and its `/test/*` endpoints, planner test coverage |
| [testing/e2e-reliability.md](testing/e2e-reliability.md) | Starved-runner signature, visual flakes as state races, the Sep 2026 first-run reliability pass, E2E gotchas and stability pitfalls |
| [testing/visual.md](testing/visual.md) | Visual regression tests: per-platform baselines, Linux baselines via Docker or CI, troubleshooting |
| [testing/evals.md](testing/evals.md) | Agent-behavior evals against the live API (`make eval`) |

## Running Tests

### Backend Tests

```bash
# Run all backend tests
make test

# Run only unit tests
make test-unit

# Run only integration tests
make test-integration

# Run with coverage report
make test-cov
```

### Frontend Tests

```bash
# Run all frontend tests (unit + component + E2E)
make test-fe

# Run only unit tests
make test-fe-unit

# Run only component tests
make test-fe-component

# Run only E2E tests (runs `make build` first)
make test-fe-e2e

# Run in watch mode (unit tests)
make test-fe-watch

# Run visual regression tests (details: testing/visual.md)
make test-fe-visual

# Update visual baselines
make test-fe-visual-update

# Linux baselines (what CI compares against; requires Docker)
make test-fe-visual-linux          # verify
make test-fe-visual-linux-update   # regenerate *-linux.png baselines
```

### All Tests

```bash
# Run all tests (backend + frontend, excluding visual)
make test-all
```

### Test Output

**Backend tests**:
```
tests/unit/test_costs.py ........                           [100%]
tests/integration/test_routes_chat.py .....                 [100%]

============================== 13 passed in 1.23s ==============================
```

**Frontend tests**:
```
✓ web/tests/unit/dom.test.ts (5 tests)
✓ web/tests/e2e/chat/streaming.spec.ts (12 tests)

 Test Files  17 passed (17)
      Tests  89 passed (89)
```

## Key Testing Patterns

### TDD for Bug Fixes

When fixing bugs, follow TDD approach:

1. **Write a failing test** that reproduces the bug
2. Run the test to confirm it fails (captures the regression)
3. Implement the fix
4. Run the test to confirm it passes
5. Run the full test suite to ensure no regressions

This ensures:
- The bug is documented as a test case
- The fix is verified to work
- The bug won't regress in the future

### Test Isolation

**Backend**:
- Each test gets its own database file
- Fixtures create fresh state
- No shared state between tests

**Frontend**:
- Each E2E test resets database via `/test/reset`
- Tests run in parallel with unique IDs
- Mock configurations are isolated per test

### Mocking Guidelines

**Backend**:
- Mock at the right level (function, class, or module)
- Use `monkeypatch` fixture for patching
- Mock external services (LLM, auth, HTTP)
- Never make real API calls

**Frontend**:
- Use mock server for API responses
- Configure mock delays per test
- Seed database directly when possible
- Test with both real and edge-case data

### Flaky Test Prevention

**Zero tolerance for flaky tests**:
- All tests MUST pass consistently
- No intermittent failures allowed
- Don't re-run hoping for pass

**Common causes and fixes**:
- **Timing issues**: Use explicit waits, not arbitrary delays
- **Dynamic content**: Use robust matchers (e.g., `toContainText` not exact length)
- **Scroll positions**: Use `isScrolledToBottom()` threshold, not exact values
- **Image loading**: Track `load` events, not just fetch completion
- **Single-sample assertions after `waitForTimeout`**: `await page.waitForTimeout(N)`
  followed by a one-shot `expect(...)` fails deterministically on a slow CI VM
  (all retries share the VM, so it doesn't even look flaky). Poll the condition
  instead: `await expect.poll(() => ..., { timeout: 10000 }).toBeLessThan(50)`.
  Real case (Aug 2026): webkit scroll-to-bottom assertion sampled 500ms after
  render on a CI VM running 5-7× slower than usual — the RAF-scheduled scroll
  hadn't run yet. Note the exception: "asserting something does NOT happen"
  (e.g., auto-scroll stays disabled) genuinely needs a fixed wait.

### Interface Extension Checklist

When you change a **shared return type** or **extend a TypeScript interface / store
shape**, every test double for it must be updated together, or tests pass against
a stale contract. Classes of places to update:

- **Agent chat return types** (`chat_batch` tuple, `stream_chat_events` final
  event) → all `mock_chat.return_value` / yielded-event mocks across `tests/`.
- **`usage_info` dict shape** → cost-tracking test fixtures that assert on token
  fields.
- **TypeScript interfaces** (e.g. `InitialRoute` in `deeplink.ts`) → the
  `toEqual` / `toHaveBeenCalledWith` assertions in the matching `*.test.ts`.
- **Zustand store state/actions** (`store.ts`) → every mock store object passed to
  `useStore.getState()` in unit/component tests.
- Search first: `grep -rn 'mock_chat\|InitialRoute\|getState.*mock\|mockStore' tests/ web/tests/`.

## Lint, Coverage & Audit Gates

CI enforces these; a green test run alone does not guarantee a green build.

- **Security lint (ruff / flake8-bandit)**: the `S` ruleset is enabled in
  [pyproject.toml](../pyproject.toml). `per-file-ignores` scope the test/script
  asserts and registry-validated SQL interpolation in `src/db/models/*` (`S608`).
  New justified findings need an inline `# noqa: SXXX - reason`.
- **Coverage floor**: `fail_under = 70` under `[tool.coverage.report]` (currently
  hovering ~72%), enforced by `make test-cov`. Adding uncovered code can fail CI
  even when all tests pass.
- **Dependency audit**: the `audit.yml` workflow fails on `pip-audit -r requirements.txt`
  findings and on `npm audit --audit-level=high` in `web/`. Locally, `make audit` runs
  the same scans but is report-only (`|| true`), so read its output.
- **TOML-ordering pitfall**: `[tool.ruff.lint.per-file-ignores]` must come **after**
  all other `[tool.ruff.lint]` keys (`select`, `ignore`). Inserting a subsection
  mid-`[tool.ruff.lint]` orphans the keys below it (e.g. silently un-ignoring
  `E501`), producing a flood of errors.

## See Also

- [API Design](architecture/api-design.md) - API endpoints, schemas and validation
- [Database](architecture/database.md) - Data layer and migrations
- [UI Components](ui/components.md) - Frontend component patterns
