/**
 * E2E tests for authentication flow
 */
import { test, expect } from '../global-setup';

test.describe('Authentication', () => {
  test('app loads successfully', async ({ page }) => {
    await page.goto('/');

    // Wait for app to initialize
    await page.waitForSelector('#app');

    // In test mode, auth is bypassed, so we should see the main UI
    await expect(page.locator('#sidebar')).toBeVisible();
    await expect(page.locator('#new-chat-btn')).toBeVisible();
  });

  test('a signed-in load does not fetch Google Sign-In', async ({ page }) => {
    // Only the login screen needs Google's script; signed-in loads skip it
    const googleRequests: string[] = [];
    page.on('request', (request) => {
      if (request.url().startsWith('https://accounts.google.com/')) {
        googleRequests.push(request.url());
      }
    });

    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    expect(googleRequests).toEqual([]);
  });

  test('shows user info in sidebar', async ({ page }) => {
    await page.goto('/');

    // Wait for app to load
    await page.waitForSelector('#new-chat-btn');

    // Should show user info after auth (test mode uses test@example.com)
    // Note: In test mode with FLASK_ENV=testing, the auth might be bypassed
    // The actual behavior depends on how the test server handles auth
    const userInfo = page.locator('#user-info');
    await expect(userInfo).toBeVisible();
  });

  test('new chat button is visible', async ({ page }) => {
    await page.goto('/');

    await page.waitForSelector('#new-chat-btn');

    const newChatBtn = page.locator('#new-chat-btn');
    await expect(newChatBtn).toBeVisible();
    await expect(newChatBtn).toBeEnabled();
  });

  test('message input is visible', async ({ page }) => {
    await page.goto('/');

    await page.waitForSelector('#message-input');

    const messageInput = page.locator('#message-input');
    await expect(messageInput).toBeVisible();
  });
});

test.describe('Mobile viewport', () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test('sidebar is hidden by default on mobile', async ({ page }) => {
    await page.goto('/');

    await page.waitForSelector('#sidebar');

    const sidebar = page.locator('#sidebar');
    // Sidebar should not have 'open' class on mobile initially
    await expect(sidebar).not.toHaveClass(/open/);
  });

  test('menu button is visible on mobile', async ({ page }) => {
    await page.goto('/');

    await page.waitForSelector('#menu-btn');

    const menuBtn = page.locator('#menu-btn');
    await expect(menuBtn).toBeVisible();
  });

  test('clicking menu button opens sidebar', async ({ page }) => {
    await page.goto('/');

    await page.waitForSelector('#menu-btn');
    await page.click('#menu-btn');

    const sidebar = page.locator('#sidebar');
    await expect(sidebar).toHaveClass(/open/);

    // Overlay should be visible
    const overlay = page.locator('.sidebar-overlay');
    await expect(overlay).toHaveClass(/visible/);
  });
});
