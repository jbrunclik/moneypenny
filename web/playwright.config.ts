import { defineConfig, devices } from '@playwright/test';

// PW_BASE_URL overrides the target server (used when the tests run inside
// the Playwright Docker container against a server on the host, e.g. for
// generating/verifying Linux visual baselines). Setting it also disables
// the managed webServer - the caller owns the server lifecycle.
// E2E_PORT runs a second suite side by side (another worktree/session); the
// managed server inherits it from this process's environment
const e2ePort = process.env.E2E_PORT || '8001';
const baseURL = process.env.PW_BASE_URL || `http://localhost:${e2ePort}`;
const manageServer = !process.env.PW_BASE_URL;

export default defineConfig({
  testDir: './tests',
  testMatch: ['e2e/**/*.spec.ts', 'visual/**/*.visual.ts'],
  // E2E tests share a single server with mocked state, but the server now supports
  // multi-tenant isolation via X-Test-Execution-Id, so we can run in parallel.
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  timeout: 30000,
  expect: {
    timeout: 10000,
  },
  // Pinned: the single-process mock server (threaded Flask + SQLite)
  // sustains ~8 concurrent contexts (4 workers x 2 browser projects).
  // '50%' on beefy machines meant ~14 contexts and ~1/600 tests timing
  // out waiting for mock responses during setup.
  workers: 4,
  // CI also writes a JSON report for the flaky-test gate (tests/flaky-gate.ts, T6)
  reporter: [
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
    ['list'],
    ...(process.env.CI ? ([['json', { outputFile: 'e2e-results.json' }]] as const) : []),
  ],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    // No test needs the app's service worker, and with it WebKit breaks the
    // harness: page.route() misses requests that pass through a worker (even
    // ones its fetch listener lets through), and Playwright's WebKit has no
    // push service - the app's pushManager.getSubscription() on a controlled
    // page never resolves (1.61) or freezes the page outright (1.64+)
    serviceWorkers: 'block',
  },

  // Only run on chromium by default - mobile tests use viewport emulation
  // Use --project=webkit to also test Safari rendering
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // Increase viewport height to reduce whitespace in visual tests
        viewport: { width: 1280, height: 1024 },
      },
    },
    {
      name: 'webkit',
      // Webkit load-flakes under full-suite contention (8 concurrent contexts):
      // rare, load-correlated failures that recover on rerun (see the search-spec
      // and archived-deeplink flakes in TODO.md). One extra retry beyond the
      // global 2 keeps a stray webkit flake from falsely reddening CI without
      // taxing the green path - retries only run on failure. Chromium stays at 2.
      retries: process.env.CI ? 3 : 0,
      use: {
        ...devices['Desktop Safari'],
        // Increase viewport height to reduce whitespace in visual tests
        viewport: { width: 1280, height: 1024 },
      },
    },
  ],

  webServer: manageServer
    ? {
        // Use .venv/bin/python if available, otherwise fall back to system python (for CI)
        command: 'cd .. && if [ -f .venv/bin/python ]; then .venv/bin/python tests/e2e-server.py; else python tests/e2e-server.py; fi',
        url: `http://localhost:${e2ePort}`,
        reuseExistingServer: !process.env.CI,
        timeout: 30000,
        // Kill any hanging servers before starting
        stdout: 'pipe',
        stderr: 'pipe',
      }
    : undefined,
});
