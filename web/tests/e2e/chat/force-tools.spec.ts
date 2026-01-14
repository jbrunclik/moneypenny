/**
 * E2E tests for force tools (search button) functionality
 */
import { test, expect } from './fixtures';

test.describe('Chat - Force Tools', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');
  });

  test('search button is visible', async ({ page }) => {
    const searchBtn = page.locator('#search-btn');
    await expect(searchBtn).toBeVisible();
  });

  test('search button toggles active state', async ({ page }) => {
    const searchBtn = page.locator('#search-btn');

    // Initially not active
    await expect(searchBtn).not.toHaveClass(/active/);

    // Click to activate
    await searchBtn.click();
    await expect(searchBtn).toHaveClass(/active/);

    // Click to deactivate
    await searchBtn.click();
    await expect(searchBtn).not.toHaveClass(/active/);
  });

  test('search button deactivates after sending message', async ({ page }) => {
    const searchBtn = page.locator('#search-btn');

    // Activate search
    await searchBtn.click();
    await expect(searchBtn).toHaveClass(/active/);

    // Send message
    await page.fill('#message-input', 'Search for something');
    await page.click('#send-btn');

    // Wait for response
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Search button should be deactivated (one-shot)
    await expect(searchBtn).not.toHaveClass(/active/);
  });
});
