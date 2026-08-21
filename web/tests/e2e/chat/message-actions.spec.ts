/**
 * E2E tests for message actions (copy, retry, structure)
 */
import { test, expect, disableStreaming, enableStreaming } from './fixtures';

test.describe('Chat - Message Actions', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Send a message first
    await page.fill('#message-input', 'Test message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });
  });

  test('copy button is visible on messages', async ({ page }) => {
    const copyBtn = page.locator('.message-copy-btn').first();
    await expect(copyBtn).toBeVisible();
  });

  test('messages have proper structure', async ({ page }) => {
    // User message
    const userMessage = page.locator('.message.user');
    await expect(userMessage).toBeVisible();
    await expect(userMessage.locator('.message-content')).toBeVisible();

    // Assistant message
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible();
    await expect(assistantMessage.locator('.message-content')).toBeVisible();
  });
});

test.describe('Chat - Message Retry', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Disable streaming for batch tests (easier to control errors)
    await disableStreaming(page);
  });

  test('failed batch send shows inline retry that resends the message', async ({ page }) => {
    // First request fails with a server error; subsequent requests pass through
    let requestCount = 0;
    await page.route('**/chat/batch', async (route) => {
      requestCount++;
      if (requestCount === 1) {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({
            error: { code: 'SERVER_ERROR', message: 'Simulated server error', retryable: true },
          }),
        });
      } else {
        await route.continue();
      }
    });

    await page.fill('#message-input', 'Test message for retry');
    await page.click('#send-btn');

    // The message stays visible, marked failed, with an inline retry action
    const failedMessage = page.locator('.message.user.message--send-failed');
    await expect(failedMessage).toBeVisible({ timeout: 10000 });
    await expect(failedMessage).toContainText('Test message for retry');

    // The input stays cleared - the message lives in the failed bubble now
    await expect(page.locator('#message-input')).toHaveValue('');

    // Retry from the message itself
    await failedMessage.locator('[data-action="retry-send"]').click();

    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });
    await expect(assistantMessage).toContainText('mock response', { ignoreCase: true });

    // Failed state cleared, no duplicate user message
    await expect(page.locator('.message--send-failed')).toHaveCount(0);
    await expect(page.locator('.message.user')).toHaveCount(1);
  });

  test('failed send is persisted to the outbox for recovery after reload', async ({ page }) => {
    await page.route('**/chat/batch', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({
          error: { code: 'SERVER_ERROR', message: 'Simulated server error', retryable: true },
        }),
      });
    });

    await page.fill('#message-input', 'Draft message for recovery');
    await page.click('#send-btn');

    await expect(page.locator('.message--send-failed')).toBeVisible({ timeout: 10000 });

    // The failed send is persisted (outbox) so it survives a reload
    const outboxContent = await page.evaluate(() => {
      const raw = localStorage.getItem('ai-chatbot-send-outbox-v1');
      if (!raw) return null;
      const entries = Object.values(JSON.parse(raw)).flat() as { content: string; status: string }[];
      return entries[0] ?? null;
    });
    expect(outboxContent?.content).toBe('Draft message for recovery');
    expect(outboxContent?.status).toBe('failed');
  });

  test('streaming error after delivery does not mark the user message unsent', async ({ page }) => {
    await enableStreaming(page);

    // The server responds with a stream (= user message was saved) that then
    // errors out. The user message must NOT get a failed/retry state.
    await page.route('**/chat/stream', async (route) => {
      const errorEvent = `event: error\ndata: ${JSON.stringify({
        type: 'error',
        message: 'Simulated streaming error',
        code: 'SERVER_ERROR',
        retryable: true,
      })}\n\n`;
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: errorEvent });
    });

    await page.fill('#message-input', 'Streaming test message for retry');
    await page.click('#send-btn');

    // An error surfaces via toast
    await expect(page.locator('.toast-error')).toBeVisible({ timeout: 10000 });

    // But the user message is delivered - no failed state, no outbox entry
    await expect(page.locator('.message.user')).toBeVisible();
    await expect(page.locator('.message--send-failed')).toHaveCount(0);
    const outboxRaw = await page.evaluate(() => localStorage.getItem('ai-chatbot-send-outbox-v1'));
    expect(outboxRaw).toBeNull();
  });
});
