/**
 * E2E tests for send-failure handling: failed sends stay visible with
 * retry/discard, survive reload, and retries are idempotent.
 */
import { test, expect, enableStreaming } from './fixtures';
import type { Page } from '@playwright/test';

const CHAT_ENDPOINTS = '**/chat/{stream,batch}';

async function blockSends(page: Page): Promise<void> {
  await page.route(CHAT_ENDPOINTS, (route) => route.abort('failed'));
}

async function restoreSends(page: Page): Promise<void> {
  await page.unroute(CHAT_ENDPOINTS);
}

test.describe('Chat - Send Failure Handling', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');
    await enableStreaming(page);
  });

  test('failed send keeps the message visible with retry and discard', async ({ page }) => {
    await blockSends(page);

    await page.fill('#message-input', 'Message into the void');
    await page.click('#send-btn');

    // The failed state appears only after the automatic retry also failed -
    // never during the auto-retry window
    await page.waitForTimeout(800);
    await expect(page.locator('.message--send-failed')).toHaveCount(0);

    const failedMessage = page.locator('.message.user.message--send-failed');
    await expect(failedMessage).toBeVisible({ timeout: 20000 });
    await expect(failedMessage).toContainText('Message into the void');
    await expect(failedMessage.locator('[data-action="retry-send"]')).toBeVisible();
    await expect(failedMessage.locator('[data-action="discard-send"]')).toBeVisible();
  });

  test('retry after connection restored delivers the message', async ({ page }) => {
    await blockSends(page);
    await page.fill('#message-input', 'Retry me');
    await page.click('#send-btn');
    await expect(page.locator('.message--send-failed')).toBeVisible({ timeout: 20000 });

    await restoreSends(page);
    await page.click('[data-action="retry-send"]');

    // The send succeeds: failed state clears and the assistant responds
    await expect(page.locator('.message.assistant')).toContainText('mock response', {
      timeout: 20000,
    });
    await expect(page.locator('.message--send-failed')).toHaveCount(0);
    // Exactly one copy of the user message (no duplicates from the retry)
    await expect(page.locator('.message.user')).toHaveCount(1);
  });

  test('failed send survives a page reload with retry available', async ({ page }) => {
    await blockSends(page);
    await page.fill('#message-input', 'Survive the reload');
    await page.click('#send-btn');
    await expect(page.locator('.message--send-failed')).toBeVisible({ timeout: 20000 });

    // Reload: the deep-link hash restores the conversation; the unconfirmed
    // send must be reconciled back into the view as failed.
    // (page.route blocks persist across reloads - lift them so the retry
    // below exercises a restored connection)
    await restoreSends(page);
    await page.reload();
    const failedMessage = page.locator('.message.user.message--send-failed');
    await expect(failedMessage).toBeVisible({ timeout: 20000 });
    await expect(failedMessage).toContainText('Survive the reload');

    // And it is still retryable after the reload
    await page.click('[data-action="retry-send"]');
    await expect(page.locator('.message.assistant')).toContainText('mock response', {
      timeout: 20000,
    });
    await expect(page.locator('.message--send-failed')).toHaveCount(0);
  });

  test('discard removes the failed message permanently', async ({ page }) => {
    await blockSends(page);
    await page.fill('#message-input', 'Discard me');
    await page.click('#send-btn');
    await expect(page.locator('.message--send-failed')).toBeVisible({ timeout: 20000 });

    await page.click('[data-action="discard-send"]');
    await expect(page.locator('.message.user')).toHaveCount(0);

    // Still gone after a reload (outbox entry was removed)
    await page.reload();
    await page.waitForSelector('#message-input', { timeout: 20000 });
    await expect(page.locator('.message.user')).toHaveCount(0);
  });
});

test.describe('Chat - Send Auto-Retry', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');
    await enableStreaming(page);
  });

  test('transient network failure is retried automatically once', async ({ page }) => {
    let attempt = 0;
    await page.route(CHAT_ENDPOINTS, (route) => {
      attempt++;
      if (attempt === 1) return route.abort('failed');
      return route.continue();
    });

    await page.fill('#message-input', 'Auto retry me');
    await page.click('#send-btn');

    // During the auto-retry window the message must stay PENDING - flashing
    // the retry/discard buttons before the automatic retry was confusing
    await page.waitForTimeout(800);
    await expect(page.locator('.message--send-failed')).toHaveCount(0);
    await expect(page.locator('.message.user.message--send-pending')).toBeVisible();

    // Delivered without any manual interaction (one automatic retry)
    await expect(page.locator('.message.assistant')).toContainText('mock response', {
      timeout: 20000,
    });
    await expect(page.locator('.message--send-failed')).toHaveCount(0);
    await expect(page.locator('.message.user')).toHaveCount(1);
  });
});
