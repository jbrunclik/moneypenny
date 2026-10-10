/**
 * A server-reported error before any text: the client ran the network-drop
 * resume and recovery anyway (~15s of a Stop button and no bubble), ended
 * with "Response may be incomplete" plus the error, and left no way to retry
 * the reply - the conversation ended on the user's message.
 */
import { test, expect, enableStreaming, failNextStream, setMockResponse, clearMockResponse } from './fixtures';

test.describe('Chat - server error before any text', () => {
  test.afterEach(async ({ page }) => {
    await clearMockResponse(page);
  });

  test('fails at once with a Retry that answers the message', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');
    await enableStreaming(page);

    await failNextStream(page);

    await page.fill('#message-input', 'Hello there');
    await page.click('#send-btn');

    const retry = page.locator('.toast .toast-action', { hasText: 'Retry' });
    await expect(retry).toBeVisible({ timeout: 3000 });
    await expect(page.locator('#send-btn.btn-stop')).toHaveCount(0);
    await expect(page.locator('.toast', { hasText: 'incomplete' })).toHaveCount(0);

    await setMockResponse(page, 'Here is the answer');
    await retry.click();
    await expect(page.locator('.message.assistant')).toContainText('Here is the answer', { timeout: 20000 });
    await expect(page.locator('.message.user')).toHaveCount(1);
  });
});
