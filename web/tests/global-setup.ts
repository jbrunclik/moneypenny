/**
 * Global setup that runs before each test file
 */
import { test as base, expect } from '@playwright/test';

import { v4 as uuidv4 } from 'uuid';

/**
 * Extended test with automatic database reset and isolation via X-Test-Execution-Id
 */
export const test = base.extend<{
  testExecutionId: string;
}>({
  testExecutionId: async ({ }, use) => {
    const id = uuidv4();
    await use(id);
  },

  context: async ({ context, testExecutionId }, use) => {
    await context.setExtraHTTPHeaders({
      'X-Test-Execution-Id': testExecutionId,
    });
    await use(context);
  },

  page: async ({ page }, use) => {
    // Reset database before each test for isolation
    // page.request uses the browser context which already has the header
    const response = await page.request.post('http://localhost:8001/test/reset');
    expect(response.ok()).toBeTruthy();

    await use(page);
  },

  request: async ({ playwright, testExecutionId }, use) => {
    const apiContext = await playwright.request.newContext({
      baseURL: 'http://localhost:8001',
      extraHTTPHeaders: {
        'X-Test-Execution-Id': testExecutionId,
      },
    });
    await use(apiContext);
    await apiContext.dispose();
  },
});

export { expect } from '@playwright/test';

/**
 * Wait for the sidebar conversation list to leave its loading state.
 *
 * Boot shows skeleton placeholders until the conversations fetch resolves
 * (since the Aug 18 "boot shows a loader, never the welcome screen" change).
 * Sidebar screenshots taken before they disappear capture skeletons instead
 * of the settled list/empty state and flake on slow CI runners.
 */
export async function waitForSidebarSettled(page: import('@playwright/test').Page): Promise<void> {
  await expect(page.locator('.conversation-skeleton')).toHaveCount(0);
}
