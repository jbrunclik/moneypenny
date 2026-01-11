import { defineConfig, devices } from '@playwright/test';

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
  workers: '50%', // Don't saturate the CPU, leave room for the python server
  reporter: [['html', { outputFolder: 'playwright-report', open: 'never' }], ['list']],
  use: {
    baseURL: 'http://localhost:8001',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
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
      use: {
        ...devices['Desktop Safari'],
        // Increase viewport height to reduce whitespace in visual tests
        viewport: { width: 1280, height: 1024 },
      },
    },
  ],

  webServer: {
    // Use .venv/bin/python if available, otherwise fall back to system python (for CI)
    command: 'cd .. && if [ -f .venv/bin/python ]; then .venv/bin/python tests/e2e-server.py; else python tests/e2e-server.py; fi',
    url: 'http://localhost:8001',
    reuseExistingServer: !process.env.CI,
    timeout: 30000,
    // Kill any hanging servers before starting
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
