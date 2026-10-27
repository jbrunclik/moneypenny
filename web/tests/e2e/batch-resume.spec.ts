/**
 * E2E tests for a batch (non-streaming) turn that outlives its page.
 *
 * The batch endpoint saves the user message before the agent runs, and the
 * server keeps running the turn after the client disconnects. A page that
 * reloads mid-turn (iPhone PWA suspended or killed) must keep waiting for the
 * reply instead of showing the message with no reply and no spinner - which
 * is what made users send it again.
 */
import { test, expect } from '../global-setup';
import { appReady } from './waits';

test.describe('Batch turn after reload', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await appReady(page);

    // Disable streaming
    const streamBtn = page.locator('#stream-btn');
    if ((await streamBtn.getAttribute('aria-pressed')) === 'true') {
      await streamBtn.click();
    }
  });

  test('page reload mid-turn waits for the reply with the spinner up', async ({ page, request }) => {
    // Keep the turn running server-side across the reload. The `request`
    // fixture carries X-Test-Execution-Id, so the delay stays in this test.
    await request.post('/test/set-batch-delay', { data: { delay_ms: 4000 } });

    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Survive a batch reload please');
    const batchRequest = page.waitForRequest('**/chat/batch');
    await page.click('#send-btn');
    await batchRequest;
    await page.waitForSelector('.message-loading');
    // The server saves the user message before the (delayed) agent call
    await expect.poll(async () => { const id = page.url().split('/conversations/')[1]; if (!id) return 0; const r = await page.request.get(`/api/conversations/${id}/messages`); return r.ok() ? ((await r.json()) as { messages: unknown[] }).messages.length : 0; }, { timeout: 5000 }).toBeGreaterThan(0);

    await page.reload();
    await appReady(page);

    // The user message is back from the server; the spinner says a reply is coming
    await expect(page.locator('.message.user')).toHaveCount(1);
    await expect(page.locator('.message-loading')).toBeVisible({ timeout: 5000 });

    const content = page.locator('.message.assistant').last().locator('.message-content');
    await expect(content).toContainText('This is a mock response to: Survive a batch reload', {
      timeout: 30000,
    });
    await expect(page.locator('.message-loading')).toHaveCount(0);
    await expect(page.locator('.message.user')).toHaveCount(1);
    // The turn's in-flight placeholder must not also be followed as another
    // device's reply (one reply, not two)
    await page.waitForTimeout(1500); // a span for a second (followed) reply to show (none must)
    await expect(page.locator('.message.assistant')).toHaveCount(1);
  });
});
