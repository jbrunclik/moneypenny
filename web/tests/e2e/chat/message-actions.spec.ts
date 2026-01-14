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

  test('retry button restores message to input and sends it', async ({ page }) => {
    // Enable error simulation mode for the next request
    await page.evaluate(() => {
      // Store the original message to verify it's restored
      (window as unknown as { __testMessage: string }).__testMessage = 'Test message for retry';
    });

    // Type a message
    await page.fill('#message-input', 'Test message for retry');

    // Intercept the chat request to make it fail with a retryable error
    await page.route('**/chat/batch', async (route) => {
      // First request fails
      const requestCount = await page.evaluate(() => {
        const count =
          ((window as unknown as { __chatRequestCount: number }).__chatRequestCount ?? 0) + 1;
        (window as unknown as { __chatRequestCount: number }).__chatRequestCount = count;
        return count;
      });

      if (requestCount === 1) {
        // First request: return a retryable error
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({
            error: {
              code: 'SERVER_ERROR',
              message: 'Simulated server error',
              retryable: true,
            },
          }),
        });
      } else {
        // Subsequent requests: pass through to actual server
        await route.continue();
      }
    });

    // Send the message
    await page.click('#send-btn');

    // Wait for error toast with retry button
    const toast = page.locator('.toast-error');
    await expect(toast).toBeVisible({ timeout: 5000 });
    await expect(toast).toContainText('Please try again');

    // Verify the retry button is present
    const retryButton = toast.locator('.toast-action');
    await expect(retryButton).toBeVisible();
    await expect(retryButton).toContainText('Retry');

    // The input should be cleared after failed send (message was added to UI)
    const textarea = page.locator('#message-input');
    await expect(textarea).toHaveValue('');

    // Click retry button
    await retryButton.click();

    // The message should be restored to the input
    await expect(textarea).toHaveValue('Test message for retry');

    // Toast should be dismissed
    await expect(toast).not.toBeVisible({ timeout: 2000 });

    // Click send again (the retry should have restored the message)
    await page.click('#send-btn');

    // Now we should get a successful response
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });
    await expect(assistantMessage).toContainText('mock response', { ignoreCase: true });
  });

  test('draft is saved on error and can be recovered on page reload', async ({ page }) => {
    // Type a message
    await page.fill('#message-input', 'Draft message for recovery');

    // Intercept the chat request to make it fail
    await page.route('**/chat/batch', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({
          error: {
            code: 'SERVER_ERROR',
            message: 'Simulated server error',
            retryable: true,
          },
        }),
      });
    });

    // Send the message
    await page.click('#send-btn');

    // Wait for error toast
    const toast = page.locator('.toast-error');
    await expect(toast).toBeVisible({ timeout: 5000 });

    // Verify draft is saved to localStorage (check store state)
    const draftMessage = await page.evaluate(() => {
      const storage = localStorage.getItem('ai-chatbot-storage');
      if (storage) {
        const parsed = JSON.parse(storage);
        return parsed.state?.draftMessage;
      }
      return null;
    });
    expect(draftMessage).toBe('Draft message for recovery');
  });

  test('streaming mode: retry button restores message to input', async ({ page }) => {
    // Enable streaming mode
    await enableStreaming(page);

    // Type a message
    await page.fill('#message-input', 'Streaming test message for retry');

    // Intercept the streaming request to make it fail with SSE error event
    let requestCount = 0;
    await page.route('**/chat/stream', async (route) => {
      requestCount++;
      if (requestCount === 1) {
        // First request: return an SSE error event
        const errorEvent = `event: error\ndata: ${JSON.stringify({
          type: 'error',
          message: 'Simulated streaming error',
          code: 'SERVER_ERROR',
          retryable: true,
        })}\n\n`;

        await route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: errorEvent,
        });
      } else {
        // Subsequent requests: pass through to actual server
        await route.continue();
      }
    });

    // Send the message
    await page.click('#send-btn');

    // Wait for error toast with retry button
    const toast = page.locator('.toast-error');
    await expect(toast).toBeVisible({ timeout: 5000 });

    // Verify the retry button is present
    const retryButton = toast.locator('.toast-action');
    await expect(retryButton).toBeVisible();
    await expect(retryButton).toContainText('Retry');

    // The input should be cleared after failed send
    const textarea = page.locator('#message-input');
    await expect(textarea).toHaveValue('');

    // Verify draft is saved to localStorage before clicking retry
    const draftMessageBeforeRetry = await page.evaluate(() => {
      const storage = localStorage.getItem('ai-chatbot-storage');
      if (storage) {
        const parsed = JSON.parse(storage);
        return parsed.state?.draftMessage;
      }
      return null;
    });
    expect(draftMessageBeforeRetry).toBe('Streaming test message for retry');

    // Click retry button
    await retryButton.click();

    // The message should be restored to the input
    await expect(textarea).toHaveValue('Streaming test message for retry');

    // Toast should be dismissed
    await expect(toast).not.toBeVisible({ timeout: 2000 });
  });
});
