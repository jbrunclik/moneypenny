# Testing

Moneypenny has comprehensive test coverage across both backend and frontend, including unit tests, integration tests, end-to-end tests, and visual regression tests.

## Table of Contents

- [Overview](#overview)
- [Backend Testing](#backend-testing)
- [Frontend Testing](#frontend-testing)
- [Running Tests](#running-tests)
- [E2E Test Server](#e2e-test-server)
- [Visual Regression Tests](#visual-regression-tests)
- [Writing New Tests](#writing-new-tests)
- [Key Testing Patterns](#key-testing-patterns)

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

## Backend Testing

### Test Structure

```
tests/
├── conftest.py                    # Shared fixtures (database, app, auth, mocks)
├── fixtures/
│   └── images.py                  # Test image generators
├── mocks/
│   └── gemini.py                  # Mock LLM response builders
├── unit/                          # Unit tests (isolated function testing)
│   ├── test_costs.py              # Cost calculations
│   ├── test_jwt_auth.py           # JWT token handling
│   ├── test_google_auth.py        # Google token verification
│   ├── test_chat_agent_helpers.py # Agent helper functions
│   ├── test_images.py             # Image processing
│   └── test_tools.py              # Agent tools (mocked externals)
├── integration/                   # Integration tests (multi-component)
│   ├── test_db_models/          # Database CRUD operations
│   ├── test_routes_auth.py        # Auth endpoints
│   ├── test_routes_conversations.py  # Conversation CRUD
│   ├── test_routes_chat.py        # Chat endpoints
│   └── test_routes_costs.py       # Cost tracking endpoints
└── e2e-server.py                  # Mock Flask server for E2E tests
```

### Key Testing Patterns (Backend)

**Isolated SQLite per test**:
- Each test gets its own database file for complete isolation
- Database fixture creates a fresh database for each test
- No shared state between tests

**Mocked external services**:
- Gemini LLM responses are mocked with proper AIMessage objects
- Google Auth token verification is mocked
- DuckDuckGo search is mocked
- HTTP requests (httpx) are mocked

**Shared fixtures** (from [../../tests/conftest.py](../../tests/conftest.py)):
```python
def test_example(client, test_user, test_conversation, auth_headers):
    # client: Flask test client
    # test_user: Pre-created user
    # test_conversation: Pre-created conversation for test_user
    # auth_headers: JWT auth headers for test_user
    response = client.get('/api/conversations', headers=auth_headers)
    assert response.status_code == 200
```

**Flask test client**:
```python
def test_endpoint(client, auth_headers):
    response = client.post('/api/endpoint',
                          headers=auth_headers,
                          json={'data': 'value'})
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
```

### Unit Tests

Unit tests focus on isolated function testing with all dependencies mocked:

```python
# tests/unit/test_costs.py
def test_calculate_cost():
    cost = calculate_token_cost(
        input_tokens=1000,
        output_tokens=500,
        model='gemini-3-flash-preview'
    )
    assert cost > 0
    assert isinstance(cost, float)
```

### Integration Tests

Integration tests verify multiple components working together:

```python
# tests/integration/test_routes_chat.py
def test_chat_endpoint(client, test_user, test_conversation, auth_headers):
    response = client.post(
        '/chat/batch',
        headers=auth_headers,
        json={
            'conversation_id': test_conversation.id,
            'message': 'Hello',
            'stream': False,
        }
    )
    assert response.status_code == 200
    data = response.get_json()
    assert 'response' in data
```

### Mock Return Value Formats (Chat Path)

When mocking the agent's chat entrypoints, the return shapes must match exactly
or downstream code (metadata extraction, cost saving) breaks.

**`ChatAgent.chat_batch`** returns a 4-tuple
`(response_text, tool_results, usage_info, result_messages)`:

```python
mock_chat.return_value = ("Response text", [], usage_info, [ai_message])
```

- `result_messages` is the full list of LangChain `BaseMessage` objects from the
  graph — sources, generated-image prompts, and memory ops are extracted from it.
- `usage_info` is a dict: `input_tokens`, `output_tokens`, `cached_input_tokens`,
  `tool_rounds`, `tool_call_count`.

**`ChatAgent.stream_chat_events`** yields events; the terminal event carries the
same payload under `result_messages` (not `metadata`):

```python
yield {
    "type": "final",
    "content": "...",
    "tool_results": [...],
    "usage_info": {...},
    "result_messages": [ai_message],
}
```

When you change either return type, update **every** mock return value across
`tests/` and `web/tests/` — see the Interface Extension Checklist below.

## Frontend Testing

### Test Structure

```
web/tests/
├── global-setup.ts                # Playwright test setup
├── unit/                          # Vitest unit tests
│   ├── setup.ts                   # Test setup (jsdom config)
│   ├── api-client.test.ts         # API client utilities
│   ├── dom.test.ts                # DOM utilities
│   ├── store.test.ts              # Zustand store
│   ├── toast.test.ts              # Toast notifications
│   └── modal.test.ts              # Modal dialogs
├── component/                     # Component tests with jsdom
│   └── Sidebar.test.ts            # Sidebar interactions
├── e2e/                           # Playwright E2E tests
│   ├── auth.spec.ts               # Authentication flow
│   ├── chat/                      # Chat functionality (split into modules)
│   │   ├── fixtures.ts            # Shared test utilities
│   │   ├── anonymous-mode.spec.ts # Anonymous mode tests
│   │   ├── attachments.spec.ts    # File attachments, upload progress
│   │   ├── batch-mode.spec.ts     # Batch mode message sending
│   │   ├── clipboard.spec.ts      # Clipboard paste/copy
│   │   ├── conversation-switch.spec.ts  # Conversation switching
│   │   ├── force-tools.spec.ts    # Force tools (search button)
│   │   ├── lightbox.spec.ts       # Image lightbox
│   │   ├── message-actions.spec.ts # Message actions (copy, retry)
│   │   ├── model-selection.spec.ts # Model selection persistence
│   │   ├── streaming.spec.ts      # Streaming, auto-scroll, stop
│   │   └── thinking-indicator.spec.ts # Thinking indicator
│   ├── conversation.spec.ts       # Conversation CRUD
│   ├── pagination.spec.ts         # Pagination
│   ├── search.spec.ts             # Full-text search
│   ├── mobile.spec.ts             # Mobile viewport tests
│   └── planner.spec.ts            # Planner feature (32 tests)
└── visual/                        # Visual regression tests
    ├── chat.visual.ts             # Chat interface screenshots
    ├── mobile.visual.ts           # Mobile layouts
    ├── error-ui.visual.ts         # Error UI
    ├── popups.visual.ts           # Popups and modals
    └── planner.visual.ts          # Planner dashboard (~30 snapshots)
```

### Key Testing Patterns (Frontend)

**Vitest for unit/component tests**:
- Fast, TypeScript-native
- Uses jsdom for DOM simulation
- No browser overhead

**Playwright for E2E tests**:
- Real browser testing (Chromium, WebKit)
- Mock server for API responses
- Parallel test execution with isolation

**E2E test isolation**:
- Each test resets database via `/test/reset` endpoint
- Tests run in parallel with unique database per test
- `X-Test-Execution-Id` header provides isolation

**Mock LLM server**:
- `tests/e2e-server.py` runs Flask with mocked Gemini responses
- Configurable delays and responses per test
- SSE streaming support

**E2E auth bypass**:
- Tests set `E2E_TESTING=true` to skip auth
- Separate from unit test mode
- No Google OAuth in E2E tests

### Unit Tests (Frontend)

Unit tests for utilities and helpers:

```typescript
// web/tests/unit/dom.test.ts
import { escapeHtml } from '../../src/utils/dom';

describe('escapeHtml', () => {
  it('escapes HTML special characters', () => {
    expect(escapeHtml('<script>alert("xss")</script>'))
      .toBe('&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;');
  });
});
```

### Component Tests

Component tests with jsdom:

```typescript
// web/tests/component/Sidebar.test.ts
import { beforeEach, describe, expect, it } from 'vitest';

describe('Sidebar', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="sidebar"></div>';
  });

  it('renders conversations', () => {
    const sidebar = document.getElementById('sidebar');
    expect(sidebar).toBeTruthy();
  });
});
```

### E2E Tests

End-to-end tests with real browser:

```typescript
// web/tests/e2e/chat/batch-mode.spec.ts
import { test, expect, disableStreaming } from './fixtures';

test('send message in batch mode', async ({ page }) => {
  await page.goto('/');
  await page.click('#new-chat-btn');
  await disableStreaming(page);
  await page.fill('#message-input', 'Hello');
  await page.click('#send-btn');

  await expect(page.locator('.message-content'))
    .toContainText('Hello');
});
```

Chat tests are split into focused modules in `web/tests/e2e/chat/`:
- `fixtures.ts` - Shared utilities (streaming toggle, message send helpers)
- `batch-mode.spec.ts` - Batch mode message sending
- `streaming.spec.ts` - Streaming mode, auto-scroll, stop button
- `model-selection.spec.ts` - Model selection and persistence
- `conversation-switch.spec.ts` - Switching conversations during requests
- And more (see directory structure above)

#### Known transient failure signature (starved runner)

There is one recurring E2E failure pattern that is NOT a code regression
(observed 4x on CI + locally through Aug 2026): a **batch of unrelated
tests failing together, most timing out at exactly the 30s test timeout or
a 20s `waitForSelector`**, including trivial tests (e.g. "rejects empty
name") — while the same commit passes locally and adjacent commits with a
superset of the changes pass on CI. Cause: the runner/mock-server being
starved under full-suite load; timing-sensitive scroll tests fail first.

How to tell it apart from a real regression (zero-tolerance still applies):
1. The failing set is broad and unrelated to the diff (a real regression
   fails a focused cluster).
2. Failures are timeouts waiting for mock-server responses, not assertion
   mismatches — check WHERE it died (`--log-failed`): before the feature
   assertion = infrastructure, at the assertion = investigate the code.
3. Re-run the failing test with `--repeat-each=3` in isolation; the
   transient passes deterministically.
4. A superset commit passing CI clears the suspect change.

If the pattern recurs frequently, the fix direction is runner resourcing
(e.g. sharding the E2E job), not test code.

#### Visual flakes are state races, not pixel noise

When a visual test passes only on retry, diff the `expected`/`actual`
attachments in the Playwright report: the difference is almost always a
whole UI element in a different state, and the fix belongs in the app or
the test's setup, never in the baseline. Root-caused examples (Sep 2026):

- **Storage page mobile: header hidden vs visible.** `navigateToStorage`
  hides the composer; the composer `ResizeObserver` saw a bottom-pinned
  (empty) list and re-pinned it in a `requestAnimationFrame`, racing the
  page's own render + `scrollTop = 0`. Fix: re-pin only when the composer
  GROWS (`composer-height.ts`), and `programmaticScrollToBottom` no longer
  opens a "programmatic" window when nothing needs scrolling.
- **Send button disabled / new conversation missing from the sidebar.**
  Tests click New Chat as soon as `#new-chat-btn` exists, i.e. while
  `loadInitialData` still has `isLoading` set: the send-button check ran
  during loading and was never re-run, and the initial conversation list
  overwrote the local `temp-*` conversation. Both are handled in
  `loadInitialData` now.
- **Alert modal 1px bottom-edge shift** (CI only, unreproducible locally):
  bounded with `maxDiffPixels: 512` - a real regression moves thousands.

The Linux baseline regeneration artifact (`/regen-baselines`) captures
whatever state the run happened to land in, so it can carry unrelated
drift; commit only the snapshots your change actually touched.

#### E2E first-run reliability (Sep 2026 pass)

The E2E job now runs **one browser project per runner** (matrix in
`test.yml`). With both projects on one 2-vCPU runner, 8 browser contexts
shared a single mock server and the suite only passed through retries -
webkit tests timing out on mock responses that were never slow in
isolation. Retries are still configured as a safety net, but the goal is
zero `flaky` in the Playwright summary; when a test needs a retry, treat
it as a bug and diff the first-attempt `error-context.md` against the code.

Races found and fixed in that pass (all reproduced from CI artifacts, not
by guessing):

- **Send button stuck disabled / temp conversation vanishing** - tests
  click New Chat before `loadInitialData` finishes (see the visual section
  above). Showed up in E2E as `page.click('#send-btn')` hitting the 30s
  test timeout (Playwright waits for the button to become enabled).
- **Image-load scroll yanked a reader who was at the top** - on WebKit a
  five-message chat is only ~155px scrollable, below the 200px "near
  bottom" tolerance, so scrollTop 0 still counted as "at bottom" when the
  scheduled scroll fired late. The genuine-scroll-up guard in
  `thumbnails.ts` now runs before that tolerance.
- **Throughput-bound assertions** - the read-from-start test streamed a
  400-line answer (2400 tokens, one DOM re-render each) and asserted
  mid-stream; it now uses a short viewport so 80 lines are "taller than the
  viewport", waits for the stream to end, and polls the position.
- **One-shot reads of async state** - `localStorage` journal cleanup read
  once right after the final render; use `expect.poll`.
- **Lazy web-font subsets** - both fonts ship as `unicode-range` subsets
  with `font-display: swap`, so a face starts loading the first time text
  uses it. A visual test injecting the first display-font heading captured
  the fallback font. The shared fixture (`global-setup.ts`) now kicks off
  `document.fonts.load()` for the faces at page load.
- **Composer stealing focus from a modal** - a send that was still settling
  re-focused `#message-input` behind an open delete confirmation (focus ring
  in the snapshot). `focusMessageInput` now no-ops while a modal is open.
- **Check-then-act on a loader** - the sidebar load-more test waited for
  the loader, then counted its dots in a second call. Hold the request with
  `page.route` (and the sync request, which delivers every conversation at
  boot) so the loading state is observable; note `page.route` cannot see
  requests that pass through the service worker on WebKit - that describe
  uses `test.use({ serviceWorkers: 'block' })`.
- **Runner CPU starvation, not the mock server** - the e2e-server's SLOW
  log showed `/test/reset` taking up to 12s on the webkit runner at only
  4-10 server threads (a reset is ~6ms in isolation; even `GET /` took
  3.8s). Four webkit contexts saturate a 2-vCPU runner. WebKit now runs as
  four shards of two workers; the server also prints `INFLIGHT` lines for
  requests still running after 3s. (Running the browsers under `nice` was
  tried and reverted - chromium went from 0 to 6 retries.)
- **"Response never arrived" was a lost message, not a slow server** - the
  Playwright trace of a failing run showed the follow-up message posted to
  `/chat/interject`, not `/chat/batch`: the active-request flag stayed set
  until the post-response cost fetch finished, so a message sent in that
  window was queued into an already-finished turn and never answered. Real
  users hit this too (fast follow-up after a reply). Both send paths now
  release the active request the moment the turn ends; batch-mode.spec has
  the regression test (delays `/cost`, sends two messages back to back).
  Lesson: when a test waits for a response that "never arrives", read the
  network trace before blaming load - `--trace on` plus the request bodies
  in `trace.zip` pinpointed this in one run.
- **Archived deep-link reload** - the test waited for `.message.assistant`,
  which also matches the streaming placeholder, so on a slow run it archived
  and reloaded before the response was saved. Wait for
  `.message.assistant:not(.streaming)` when the next step depends on the
  turn being persisted (79 bare waits remain in the suite; most are in
  batch-mode tests, where no placeholder exists).
- **Smooth scroll-to-bottom fought a user scroll-up** - `scrollToBottom`'s
  animator now stops when the position moves against it (up); it keeps
  going when scroll anchoring nudges it down as content above loads.

### Planner Tests

The Planner feature has comprehensive E2E and visual test coverage in [../../web/tests/e2e/planner.spec.ts](../../web/tests/e2e/planner.spec.ts) and [../../web/tests/visual/planner.visual.ts](../../web/tests/visual/planner.visual.ts).

#### E2E Test Coverage (32 tests)

**Sidebar Entry Visibility:**
- Shows planner entry when Todoist connected
- Shows planner entry when Google Calendar connected
- Shows planner entry when both integrations connected
- Hides planner entry when no integrations connected

**Navigation:**
- Navigates to planner via sidebar click
- Navigates to planner via deep link (`#/planner`)
- Browser back from planner returns to previous view
- Planner entry has active state when on planner view

**Dashboard Display:**
- Displays dashboard with events and tasks
- Displays overdue tasks section when present
- Shows dashboard with partial integrations (e.g., only calendar connected)

**Actions:**
- Refresh button triggers dashboard reload
- Reset button resets conversation

**Week Section:**
- Week section is collapsible (details element)

**Copy to Clipboard:**
- Can copy event item to clipboard (skipped on WebKit due to clipboard API limitations)

**Empty States:**
- Shows empty state when no events or tasks

**Error States:**
- Shows error message when integration has error

#### Visual Test Coverage (~30 snapshots)

Comprehensive pixel-perfect snapshots across:
- Sidebar entry states (default, hover, active, hidden)
- Dashboard layouts (desktop, mobile, iPad)
- All sections (overdue, today, tomorrow, week)
- Item states (default, hover, priority indicators P1-P4)
- Actions (refresh/reset buttons)
- Integration states (connected/disconnected)
- Error and empty states
- Loading state

#### Test Patterns

**Integration Mocking:**
```typescript
// Set planner integration status
await page.request.post('/test/set-planner-integrations', {
  data: { todoist: true, calendar: false },
});
```

**Custom Dashboard Data:**
```typescript
// Set custom dashboard for testing
await page.request.post('/test/set-planner-dashboard', {
  data: {
    dashboard: {
      days: [...],
      overdue_tasks: [...],
      todoist_connected: true,
      calendar_connected: true,
      todoist_error: null,
      calendar_error: null,
    },
  },
});
```

**Strict Mode Handling:**
```typescript
// Use .first() when multiple elements match
await expect(page.locator('.dashboard-day').first()).toBeVisible();
await expect(page.locator('.planner-item').first()).toBeVisible();
```

**WebKit Clipboard Workaround:**
```typescript
// Skip clipboard tests on WebKit
test('can copy event item to clipboard', async ({ page, browserName }) => {
  test.skip(browserName === 'webkit', 'Webkit does not support clipboard permissions');

  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  // ... test implementation
});
```

#### Backend Planner Tests

**Unit Tests** ([../../tests/unit/test_planner.py](../../tests/unit/test_planner.py)):
- Dashboard data formatting
- Date range calculations
- Task priority handling
- Event/task merging logic

**Integration Tests** ([../../tests/integration/test_routes_planner.py](../../tests/integration/test_routes_planner.py)):
- `GET /api/planner` (dashboard endpoint)
- `GET /api/planner/conversation` (get or create planner conversation)
- `POST /api/planner/reset` (reset conversation)
- Integration error handling
- Dashboard caching

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

# Run only E2E tests
make test-fe-e2e

# Run in watch mode (unit tests)
make test-fe-watch

# Run visual regression tests
make test-fe-visual

# Update visual baselines
make test-fe-visual-update

# Linux baselines (what CI compares against; requires Docker)
make test-fe-visual-linux          # verify
make test-fe-visual-linux-update   # regenerate *-linux.png baselines
```

**Visual baselines are per-platform.** Local development on macOS produces
`*-darwin.png` baselines (chromium + webkit); CI runs the suite inside the
Playwright Docker container (`mcr.microsoft.com/playwright:v<version>-jammy`,
version taken from `@playwright/test` in `web/package.json`) and compares
against the committed `*-linux.png` baselines. The CI/container runs are
**chromium-only** - webkit inside the Linux container is flaky in ways the
darwin runs are not, so Safari coverage stays local. Both sets live in
`web/tests/visual/*.visual.ts-snapshots/` and both must be regenerated
after intentional UI changes:

```bash
make test-fe-visual-update          # darwin (local)
make test-fe-visual-linux-update    # linux (Docker; used by CI)
```

The Linux run works by starting the e2e mock server on the host and
pointing the container at it via `PW_BASE_URL` (which also disables
Playwright's managed webServer - see `scripts/visual_linux.sh`). If the
Playwright version is bumped, the Docker image tag follows automatically,
but all Linux baselines must be regenerated.

**No local Docker?** Trigger the `Update Visual Baselines (Linux)`
workflow instead (`gh workflow run "Update Visual Baselines (Linux)"`).
It regenerates the baselines on a GitHub runner - the exact environment
the CI visual job uses - and uploads them as a `linux-baselines`
artifact (branch protection blocks bot pushes); download it with
`gh run download <run-id> -n linux-baselines -D web/tests/visual/`,
then commit. This is also the most
reliable option in general since it cannot drift from CI (local Docker
on Apple Silicon runs the arm64 image unless forced to amd64).

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
✓ web/tests/e2e/chat.spec.ts (12 tests)

 Test Files  17 passed (17)
      Tests  89 passed (89)
```

## E2E Test Server

The E2E test server ([../../tests/e2e-server.py](../../tests/e2e-server.py)) is a Flask app that mocks external services for frontend E2E tests.

### Features

- **Mock LLM**: Returns mock responses with proper AIMessage objects for LangGraph
- **SSE Streaming**: Streams tokens word-by-word via Server-Sent Events (default 10ms delay)
- **Auth bypass**: `E2E_TESTING=true` skips Google auth and JWT validation
- **Rate limiting disabled**: `RATE_LIMITING_ENABLED=false` prevents throttling
- **Database reset**: `/test/reset` endpoint clears database between tests
- **Database seeding**: `/test/seed` endpoint creates conversations/messages directly
- **Parallel test isolation**: Each test gets its own database via `X-Test-Execution-Id` header

### Parallel Test Execution

Tests run in parallel with full isolation:

1. **Test fixture**: `global-setup.ts` provides a `testExecutionId` fixture using UUID
2. **Header propagation**: The ID is sent with all API requests via `extraHTTPHeaders`
3. **Template databases**: A pre-migrated template DB is created once at startup
4. **Per-test databases**: Each test context copies the template (fast) instead of running migrations
5. **Thread-safe context**: A lock ensures concurrent test creation doesn't cause race conditions
6. **Mock config isolation**: Each test context has its own mock configuration

### Test Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/test/reset` | POST | Clear database for test isolation |
| `/test/seed` | POST | Seed conversations/messages directly |
| `/test/set-stream-delay` | POST | Set delay between streamed tokens (ms) |
| `/test/set-batch-delay` | POST | Set delay for batch responses (ms) |
| `/test/set-mock-response` | POST | Set custom response text |
| `/test/set-emit-thinking` | POST | Enable/disable thinking events |
| `/test/set-search-results` | POST | Set mock search results |
| `/test/clear-search-results` | POST | Clear mock search results |

### Using Database Seeding

Seed conversations directly instead of creating via UI (much faster):

```typescript
// Seed 20 conversations directly
const conversations = Array.from({ length: 20 }, (_, i) => ({
  title: `Conversation ${i + 1}`,
  messages: [
    { role: 'user', content: `User message ${i + 1}` },
    { role: 'assistant', content: `Response ${i + 1}` },
  ],
}));
await page.request.post('/test/seed', {
  data: { conversations }
});
await page.reload(); // Reload to see seeded data
```

### Manual E2E Test Execution

To run E2E tests manually:

```bash
# Terminal 1: Start mock server
cd web && python ../tests/e2e-server.py

# Terminal 2: Run tests
cd web && npx playwright test
```

### E2E Gotchas (Streaming, Service Workers, Media)

- **E2E serves BUILT assets** — run `npm run build` after every `web/src` change
  before running specs, or you test the stale bundle.
- **Streaming outruns assertions**: the default mock stream delay is ~10ms/token,
  so the stream finishes before any mid-stream click/assertion. Specs that must
  observe streaming state set a larger delay via `POST /test/set-stream-delay`
  (per-execution-id isolated).
- **Service worker blocks route mocks**: the app registers `/sw.js`
  ([src/app.py](../../src/app.py)), and `page.route()` does **not** intercept
  service-worker-mediated fetches. Any spec that mocks API responses must opt out
  with `test.use({ serviceWorkers: 'block' })` (see
  `web/tests/e2e/chat/attachments.spec.ts`).
- **Config-shrinking route mocks race app init**: after `goto`, await the config
  response (e.g. `waitForResponse('**/api/config/upload')`) before acting, or the
  store still holds defaults.
- **libmagic video detection**: production validation uses `magic.from_buffer`,
  which can return `application/octet-stream` for real video containers — hence
  the `_matches_video_signature()` fallback in
  [src/utils/files.py](../../src/utils/files.py). Hand-crafted `ftyp` headers are
  not enough; use real (tiny, ffmpeg-generated) fixtures under `tests/fixtures/`.
- **Stop button never satisfies Playwright actionability**: `#send-btn.btn-stop`
  has an infinite CSS pulse animation, so use `click({ force: true })` and assert
  the resulting effect rather than the button state.

## Visual Regression Tests

Visual tests capture screenshots and compare against baselines pixel-by-pixel.

### When to Run Visual Tests

Run visual tests after intentional UI changes:

```bash
# Run visual tests against baselines
make test-fe-visual

# Update baselines after UI changes
make test-fe-visual-update
```

**Note**: Visual tests are intentionally excluded from `make test-fe` because they:
- Compare screenshots pixel-by-pixel and can fail due to font rendering differences
- Require baseline updates when UI changes intentionally
- Run slower than functional tests

### Baseline Locations

Baselines are stored in snapshot directories:

- `web/tests/visual/chat.visual.ts-snapshots/` - Desktop chat interface
- `web/tests/visual/mobile.visual.ts-snapshots/` - Mobile/iPad layouts
- `web/tests/visual/error-ui.visual.ts-snapshots/` - Error UI
- `web/tests/visual/popups.visual.ts-snapshots/` - Popups and modals

### When to Update Baselines

Update baselines after:
- Intentional CSS changes
- Component structure modifications
- Responsive breakpoint changes
- Design system updates

Run `make test-fe-visual-update` and commit the new baseline screenshots with your UI changes.

### Troubleshooting Visual Test Failures

1. **Check diff images**: Open `web/playwright-report/index.html` to see visual diffs
2. **Verify viewport sizes**: Ensure tests run with consistent viewport dimensions
3. **Font rendering**: Font rendering differences between machines can cause false failures
4. **Ignore if expected**: If changes are intentional, update baselines

### Visual Test Example

```typescript
// web/tests/visual/chat.visual.ts
import { test } from '@playwright/test';

test('chat interface', async ({ page }) => {
  await page.goto('/');
  await page.click('[data-testid="new-chat"]');

  // Wait for UI to stabilize
  await page.waitForLoadState('networkidle');

  // Capture screenshot
  await expect(page).toHaveScreenshot('chat-interface.png');
});
```

## Writing New Tests

### Backend Tests

**1. Unit tests** for pure functions in `tests/unit/`:

```python
# tests/unit/test_mymodule.py
import pytest
from src.mymodule import my_function

def test_my_function():
    result = my_function(input_value)
    assert result == expected_value
```

**2. Integration tests** for API endpoints in `tests/integration/`:

```python
# tests/integration/test_routes_myendpoint.py
def test_my_endpoint(client, auth_headers):
    response = client.get('/api/myendpoint', headers=auth_headers)
    assert response.status_code == 200
```

**3. Use existing fixtures** from conftest.py:

```python
def test_with_fixtures(client, test_user, auth_headers, mock_gemini_llm):
    # test_user: Pre-created user
    # auth_headers: JWT headers for test_user
    # mock_gemini_llm: Mocked LLM responses
    pass
```

**4. Never make real API calls** - mock at the right level:

```python
@pytest.fixture
def mock_external_api(monkeypatch):
    def mock_call(*args, **kwargs):
        return {'status': 'success'}
    monkeypatch.setattr('mymodule.external_api_call', mock_call)
    return mock_call
```

### Frontend Tests

**1. Unit tests** for utilities in `web/tests/unit/`:

```typescript
// web/tests/unit/myutil.test.ts
import { describe, expect, it } from 'vitest';
import { myFunction } from '../../src/utils/myutil';

describe('myFunction', () => {
  it('does something', () => {
    expect(myFunction(input)).toBe(expected);
  });
});
```

**2. Component tests** in `web/tests/component/`:

```typescript
// web/tests/component/MyComponent.test.ts
import { beforeEach, describe, expect, it } from 'vitest';

describe('MyComponent', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="my-component"></div>';
  });

  it('renders correctly', () => {
    const el = document.getElementById('my-component');
    expect(el).toBeTruthy();
  });
});
```

**3. E2E tests** in `web/tests/e2e/`:

```typescript
// web/tests/e2e/myfeature.spec.ts
import { test, expect } from '@playwright/test';

test('user can do something', async ({ page }) => {
  await page.goto('/');
  // Interact with page
  await expect(page.locator('.result')).toBeVisible();
});
```

**4. Mobile tests** - use mobile viewport:

```typescript
test.use({ viewport: { width: 375, height: 812 } }); // iPhone X

test('mobile feature', async ({ page }) => {
  // Test will use mobile viewport
});
```

**5. Both batch and streaming modes** are fully supported:

```typescript
test('works in batch mode', async ({ page }) => {
  await page.click('[data-testid="stream-toggle"]'); // Disable streaming
  // Test batch mode
});

test('works in streaming mode', async ({ page }) => {
  // Streaming is default
  // Test streaming mode
});
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
  [pyproject.toml](../../pyproject.toml). `per-file-ignores` scope the test/script
  asserts and registry-validated SQL interpolation in `src/db/models/*` (`S608`).
  New justified findings need an inline `# noqa: SXXX - reason`.
- **Coverage floor**: `fail_under = 70` under `[tool.coverage.report]` (currently
  hovering ~72%), enforced by `make test-cov`. Adding uncovered code can fail CI
  even when all tests pass.
- **npm audit**: `make audit` gates the frontend tree at `--audit-level=high`.
- **TOML-ordering pitfall**: `[tool.ruff.lint.per-file-ignores]` must come **after**
  all other `[tool.ruff.lint]` keys (`select`, `ignore`). Inserting a subsection
  mid-`[tool.ruff.lint]` orphans the keys below it (e.g. silently un-ignoring
  `E501`), producing a flood of errors.

## See Also

- [Backend Architecture](backend/architecture.md) - Backend code organization
- [API Documentation](backend/api.md) - API endpoints and schemas
- [UI Components](ui/components.md) - Frontend component patterns
- [Error Handling](backend/error-handling.md) - Error handling strategies


## E2E Stability Pitfalls (Aug 2026)

- **E2E always tests the LAST `make build`, not your source**: the e2e
  server serves the production bundle from `static/assets/`. After any
  frontend change, run `make build` before Playwright or you'll debug the
  previous build's behavior (symptom: your new classes/log lines never
  appear in the browser).
- **`page.route` interceptions persist across `page.reload()`**: a test
  that blocks requests and then reloads is still blocked after the reload -
  `unroute` explicitly when the post-reload phase needs a working network.
- **Stale e2e server after `make build`**: Playwright reuses a running
  server (`reuseExistingServer`). A server started before a rebuild serves
  the old bundle while `/api/version` etc. reflect old state - kill the
  listener first: `lsof -tiTCP:8001 -sTCP:LISTEN | xargs kill`.
- **Parallel-load setup timeouts**: the mock server (threaded Flask +
  SQLite) sustains ~8 concurrent browser contexts; beyond that, setup
  waits (`waiting for locator('.message.assistant').nth(N)`) time out
  ~1/600 tests. Workers are therefore PINNED to 4 in
  `playwright.config.ts` - don't raise without 5x consecutive clean
  full-suite runs at the higher value.
- **Version banner in accessibility snapshots**: `.version-banner` is
  always in the DOM (hidden via transform), so it appears in every
  Playwright error-context snapshot - it is NOT evidence the banner was
  shown.
