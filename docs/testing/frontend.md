# Frontend and E2E Testing

Vitest unit/component tests and Playwright E2E tests against the mock server. Run them with `make test-fe` (see [Testing](../testing.md) for all commands). CI-reliability lessons live in [E2E Reliability](e2e-reliability.md); screenshot tests in [Visual Regression Tests](visual.md).

## Test Structure

```
web/tests/
├── global-setup.ts                # Playwright fixtures (testExecutionId, font preload)
├── unit/                          # Vitest unit tests (jsdom), ~45 files, e.g.
│   ├── setup.ts                   # Test setup (jsdom config)
│   ├── api-client.test.ts         # API client utilities
│   ├── dom.test.ts                # DOM utilities
│   ├── store.test.ts              # Zustand store
│   ├── messaging-store.test.ts    # Store-authoritative assistant messages
│   ├── stream-done.test.ts        # Stream completion handling
│   └── routing-race.test.ts       # Navigation token pattern
├── component/                     # Component tests with jsdom
│   ├── Sidebar.test.ts            # Sidebar interactions
│   ├── ChatHeader.test.ts         # Chat header
│   └── Messages.test.ts           # Message rendering
├── e2e/                           # Playwright E2E tests
│   ├── chat/                      # Chat functionality (split into modules)
│   │   ├── fixtures.ts            # Shared utilities (disableStreaming, sendMessageAndWait)
│   │   ├── batch-mode.spec.ts     # Batch mode message sending
│   │   ├── streaming.spec.ts      # Streaming, auto-scroll, stop
│   │   ├── rerun.spec.ts          # Retry / re-run of a turn
│   │   ├── send-failure.spec.ts   # Failed sends and the outbox
│   │   ├── thinking-indicator.spec.ts # Thinking indicator
│   │   └── ...                    # attachments, clipboard, lightbox, pdf-viewer, ...
│   ├── stream-resume.spec.ts      # Resumable streams after reload
│   ├── stream-recovery.spec.ts    # Placeholder / poll-fallback recovery
│   ├── compaction.spec.ts         # Conversation compaction chip/divider
│   ├── conversation.spec.ts       # Conversation CRUD
│   ├── deeplink.spec.ts           # Deep links and routing
│   ├── planner.spec.ts            # Planner feature
│   └── ...                        # agents, search, sync, mobile, settings, ...
└── visual/                        # Visual regression tests (see visual.md)
    ├── chat.visual.ts             # Chat interface screenshots
    ├── mobile.visual.ts           # Mobile layouts
    └── ...                        # agents, planner, popups, search, sports, ...
```

## Key Testing Patterns (Frontend)

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

## Unit Tests (Frontend)

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

## Component Tests

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

## E2E Tests

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
- `rerun.spec.ts` / `send-failure.spec.ts` - Re-running a turn, failed sends
- And more (see directory structure above)

## E2E Test Server

The E2E test server ([tests/e2e-server.py](../../tests/e2e-server.py)) is a Flask app that mocks external services for frontend E2E tests.

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
| `/test/set-emit-retry` | POST | Emit a `retry` status event, held for `hold_ms` |
| `/test/clear-mock-response` | POST | Restore the default mock response |
| `/test/simulate-error` / `/test/simulate-timeout` | POST | Error-UI and timeout paths |
| `/test/set-search-results` | POST | Set mock search results |
| `/test/clear-search-results` | POST | Clear mock search results |
| `/test/set-grounding-result` | POST | Canned grounding outcome (`annotations`, `summary`) for the next turns; call it AFTER the page fixture, whose `/test/reset` clears per-test mock config |
| `/test/set-planner-*`, `/test/set-agent*`, `/test/set-kv-store-data`, `/test/set-sports-programs`, ... | POST | Feature fixtures - see the `@test_bp.route` list in `tests/e2e-server.py` |

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

## Writing New Frontend Tests

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
  await disableStreaming(page); // toggles #stream-btn off (chat/fixtures.ts)
  // Test batch mode
});

test('works in streaming mode', async ({ page }) => {
  // Streaming is default
  // Test streaming mode
});
```

## Planner Tests

The Planner feature has comprehensive E2E and visual test coverage in [web/tests/e2e/planner.spec.ts](../../web/tests/e2e/planner.spec.ts) and [web/tests/visual/planner.visual.ts](../../web/tests/visual/planner.visual.ts).

### E2E Test Coverage (23 tests)

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

### Visual Test Coverage (24 snapshots)

Comprehensive pixel-perfect snapshots across:
- Sidebar entry states (default, hover, active, hidden)
- Dashboard layouts (desktop, mobile, iPad)
- All sections (overdue, today, tomorrow, week)
- Item states (default, hover, priority indicators P1-P4)
- Actions (refresh/reset buttons)
- Integration states (connected/disconnected)
- Error and empty states
- Loading state

### Test Patterns

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

Backend planner tests: see [Backend Testing](backend.md#planner-tests-backend).

## Key Files

- [web/playwright.config.ts](../../web/playwright.config.ts) - projects, per-project retries, pinned workers, managed web server
- [web/tests/global-setup.ts](../../web/tests/global-setup.ts) - `testExecutionId` fixture and shared page setup
- [web/tests/e2e/chat/fixtures.ts](../../web/tests/e2e/chat/fixtures.ts) - chat helpers
- [tests/e2e-server.py](../../tests/e2e-server.py) - mock Flask server and `/test/*` endpoints

## See Also

- [Testing](../testing.md) - commands, TDD, isolation and mocking rules
- [E2E Reliability](e2e-reliability.md) - failure signatures, races fixed, gotchas
- [Visual Regression Tests](visual.md) - screenshot baselines
