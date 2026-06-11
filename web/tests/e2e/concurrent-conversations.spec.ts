/**
 * E2E tests for concurrent conversations: a streaming response must block
 * only its own conversation - the user can switch away, create a new chat,
 * and converse there while the first stream completes in the background.
 */
import { test, expect } from '../global-setup';

test.describe('Concurrent conversations', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    const streamBtn = page.locator('#stream-btn');
    if ((await streamBtn.getAttribute('aria-pressed')) === 'false') {
      await streamBtn.click();
    }
  });

  test('can chat in a new conversation while another streams', async ({ page, request }) => {
    await request.post('/test/set-stream-delay', { data: { delay_ms: 400 } });

    // Conversation A: slow stream
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Conversation A long answer');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant.streaming', { timeout: 10000 });

    // Create conversation B while A is still streaming - input must be usable
    await page.click('#new-chat-btn');
    await expect(page.locator('#message-input')).toBeEnabled({ timeout: 5000 });

    await page.fill('#message-input', 'Conversation B hello');
    // With text present the send button must be enabled (it stays disabled
    // for empty input by design)
    await expect(page.locator('#send-btn')).toBeEnabled();
    await page.click('#send-btn');

    // B gets its own answer while A still runs in the background
    const contentB = page.locator('.message.assistant').last().locator('.message-content');
    await expect(contentB).toContainText('This is a mock response to: Conversation B hello', {
      timeout: 30000,
    });

    // Switch back to A: its full answer must be there (completed in
    // background, no incomplete state, no lost done event)
    await page.locator('.conversation-item').last().click();
    const contentA = page.locator('.message.assistant').last().locator('.message-content');
    await expect(contentA).toContainText('This is a mock response to: Conversation A long answer', {
      timeout: 30000,
    });
    await expect(page.locator('.message.assistant.message-incomplete')).toHaveCount(0);
  });

  test('same conversation still blocks double-send (stop mode)', async ({ page, request }) => {
    await request.post('/test/set-stream-delay', { data: { delay_ms: 400 } });

    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Slow answer please');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant.streaming', { timeout: 10000 });

    // While THIS conversation streams, the send button is in stop mode
    await expect(page.locator('#send-btn.btn-stop')).toBeVisible({ timeout: 5000 });
  });
});
