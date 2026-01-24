/**
 * E2E tests for stream recovery functionality
 *
 * These tests verify:
 * - Recovery from visibility changes during streaming
 * - UI state after recovery (toast messages, message display)
 * - Edge cases (user abort, quick return)
 *
 * Note: Some scenarios like actual network drops are difficult to simulate
 * in E2E tests. Those are better covered by unit tests.
 */
import { test, expect } from '../global-setup';

test.describe('Stream Recovery - Visibility Changes', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Enable streaming for these tests
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'false') {
      await streamBtn.click();
    }
  });

  test('recovers message after page hidden during stream', async ({ page }) => {
    // Create a conversation and start streaming
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Tell me a short story');
    await page.click('#send-btn');

    // Wait for streaming to start
    await page.waitForSelector('.message.assistant.streaming', { timeout: 10000 });

    // Simulate page becoming hidden (like phone lock or app switch)
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Wait for the stream to likely complete on server side
    await page.waitForTimeout(3000);

    // Simulate page becoming visible again
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Wait for recovery or stream completion
    await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 30000 });

    // The message should be visible and have content
    const assistantMessage = page.locator('.message.assistant').last();
    await expect(assistantMessage).toBeVisible();
    const content = await assistantMessage.locator('.message-content').textContent();
    expect(content?.trim()).not.toBe('');
  });

  test('no recovery if stream completed before hide', async ({ page }) => {
    // Create a conversation with a quick response
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Say hi');
    await page.click('#send-btn');

    // Wait for streaming to complete
    await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 15000 });

    // Now simulate visibility change (after stream is done)
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await page.waitForTimeout(500);

    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // No recovery toast should appear (nothing to recover)
    await page.waitForTimeout(1000);
    const recoveryToast = page.locator('.toast-info:has-text("Recovering")');
    await expect(recoveryToast).toHaveCount(0);

    // Original message should still be there
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toHaveCount(1);
    await expect(assistantMessage).not.toHaveClass(/streaming/);
  });

  test('no recovery for user-initiated abort', async ({ page }) => {
    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Write me a very long essay about the history of computing');
    await page.click('#send-btn');

    // Wait for streaming to start
    await page.waitForSelector('.message.assistant.streaming', { timeout: 10000 });

    // Click the stop button to abort
    const stopBtn = page.locator('#stop-btn');
    if (await stopBtn.isVisible()) {
      await stopBtn.click();
    } else {
      // In some implementations the send button becomes stop during streaming
      const sendBtn = page.locator('#send-btn');
      await sendBtn.click();
    }

    // Wait a moment for abort to process
    await page.waitForTimeout(500);

    // Simulate visibility change
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await page.waitForTimeout(500);

    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // No recovery toast should appear - user abort clears pending recovery
    await page.waitForTimeout(1000);
    const recoveryToast = page.locator('.toast-info:has-text("Recovering")');
    await expect(recoveryToast).toHaveCount(0);

    // Note: When user aborts, the streaming message is removed from UI.
    // The key assertion is that no recovery is attempted after visibility change.
  });

  test('works on mobile viewport', async ({ page }) => {
    // Set mobile viewport
    await page.setViewportSize({ width: 375, height: 812 });

    // Open sidebar on mobile
    const menuBtn = page.locator('#menu-btn');
    await menuBtn.click();

    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Hello from mobile');
    await page.click('#send-btn');

    // Wait for streaming to start
    await page.waitForSelector('.message.assistant.streaming', { timeout: 10000 });

    // Simulate app going to background (visibility hidden)
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Wait for response to complete on server
    await page.waitForTimeout(3000);

    // Simulate app coming back to foreground
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Wait for recovery or stream completion
    await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 30000 });

    // Message should be visible with content
    const assistantMessage = page.locator('.message.assistant').last();
    await expect(assistantMessage).toBeVisible();
  });
});

test.describe('Stream Recovery - Quick Return', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Enable streaming
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'false') {
      await streamBtn.click();
    }
  });

  test('no recovery triggered for very short hide duration', async ({ page }) => {
    // Create conversation and start streaming
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test quick hide');
    await page.click('#send-btn');

    // Wait for streaming to start
    await page.waitForSelector('.message.assistant.streaming', { timeout: 10000 });

    // Very quick hide/show cycle (less than 500ms)
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await page.waitForTimeout(100); // Very short - less than STREAM_RECOVERY_MIN_HIDDEN_MS

    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // No recovery toast should appear (hidden too briefly)
    await page.waitForTimeout(500);
    const recoveryToast = page.locator('.toast-info:has-text("Recovering")');
    await expect(recoveryToast).toHaveCount(0);

    // Stream should continue normally
    await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 30000 });
  });
});

test.describe('Stream Recovery - Edge Cases', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Enable streaming
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'false') {
      await streamBtn.click();
    }
  });

  test('handles multiple visibility changes during stream', async ({ page }) => {
    // Create conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Tell me about space exploration');
    await page.click('#send-btn');

    // Wait for streaming to start
    await page.waitForSelector('.message.assistant.streaming', { timeout: 10000 });

    // Multiple hide/show cycles
    for (let i = 0; i < 3; i++) {
      await page.evaluate(() => {
        Object.defineProperty(document, 'visibilityState', {
          value: 'hidden',
          writable: true,
          configurable: true,
        });
        document.dispatchEvent(new Event('visibilitychange'));
      });

      await page.waitForTimeout(200);

      await page.evaluate(() => {
        Object.defineProperty(document, 'visibilityState', {
          value: 'visible',
          writable: true,
          configurable: true,
        });
        document.dispatchEvent(new Event('visibilitychange'));
      });

      await page.waitForTimeout(200);
    }

    // Wait for stream to complete
    await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 30000 });

    // Should have a valid message
    const assistantMessage = page.locator('.message.assistant').last();
    const content = await assistantMessage.locator('.message-content').textContent();
    expect(content?.trim()).not.toBe('');
  });

  test('handles conversation switch during recovery', async ({ page }) => {
    // Create first conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First conversation message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 15000 });

    // Create second conversation and start streaming
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second conversation - long response please');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant.streaming', { timeout: 10000 });

    // Simulate hide
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await page.waitForTimeout(1000);

    // Simulate show
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Quickly switch to first conversation while recovery might be happening
    const convItems = page.locator('.conversation-item-wrapper');
    await convItems.last().click(); // First conversation is at the bottom

    // Wait for conversation switch
    await page.waitForSelector('.message.user >> text=First conversation message');

    // Should see the first conversation's messages without issues
    const userMessages = page.locator('.message.user');
    await expect(userMessages.first()).toContainText('First conversation message');
  });
});
