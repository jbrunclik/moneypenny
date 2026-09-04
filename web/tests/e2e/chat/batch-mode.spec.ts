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

  test('a follow-up sent right after a response starts a new turn (not an interjection)', async ({
    page,
  }) => {
    // Regression: the active-request flag used to stay set until the
    // post-response cost fetch finished, so a message sent in that window was
    // routed to /chat/interject - queued into an already-finished turn and
    // never answered. Slow the cost fetch down to widen the window.
    await page.route('**/api/conversations/*/cost', async (route) => {
      await new Promise((r) => setTimeout(r, 1500));
      await route.continue();
    });
    const interjections: string[] = [];
    page.on('request', (req) => {
      if (req.url().includes('/chat/interject')) interjections.push(req.url());
    });

    await page.fill('#message-input', 'First');
    await page.click('#send-btn');
    await expect(page.locator('.message.assistant')).toHaveCount(1, { timeout: 10000 });

    // Immediately follow up, while the cost fetch for turn one is still pending
    await page.fill('#message-input', 'Second');
    await page.click('#send-btn');
    await expect(page.locator('.message.assistant')).toHaveCount(2, { timeout: 10000 });
    await expect(page.locator('.message.assistant').nth(1)).toContainText('Second');
    expect(interjections).toEqual([]);
  });
});
