/**
 * E2E tests for batch mode message sending
 */
import { test, expect, disableStreaming } from './fixtures';

test.describe('Chat - Batch Mode', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Disable streaming for batch tests
    await disableStreaming(page);
  });

  test('sends message and receives batch response', async ({ page }) => {
    await page.fill('#message-input', 'What is 2+2?');
    await page.click('#send-btn');

    // Wait for response (loading indicator may appear briefly but mock is fast)
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });

    // Response should contain mock text
    await expect(assistantMessage).toContainText('mock response', { ignoreCase: true });
  });

  test('shows both user and assistant messages', async ({ page }) => {
    await page.fill('#message-input', 'Hello!');
    await page.click('#send-btn');

    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    const userMessage = page.locator('.message.user');
    const assistantMessage = page.locator('.message.assistant');

    await expect(userMessage).toBeVisible();
    await expect(assistantMessage).toBeVisible();
    await expect(userMessage).toContainText('Hello!');
  });
});
