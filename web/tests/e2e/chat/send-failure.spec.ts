/**
 * E2E tests for send-failure handling: failed sends stay visible with
 * retry/discard, survive reload, and retries are idempotent.
 */
import { test, expect, enableStreaming } from './fixtures';
import type { Page } from '@playwright/test';
import { appReady } from '../waits';

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
    await appReady(page);
    await page.click('#new-chat-btn');
    await enableStreaming(page);
  });

  test('failed send keeps the message visible with retry and discard', async ({ page }) => {
    await blockSends(page);

    await page.fill('#message-input', 'Message into the void');
    await page.click('#send-btn');

    // The failed state appears only after the automatic retry also failed -
    // never during the auto-retry window
    await page.waitForTimeout(800); // inside the auto-retry window: the failed state must not show yet
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

  test('a failed send is resent on its own after a reload', async ({ page }) => {
    await blockSends(page);
    await page.fill('#message-input', 'Survive the reload');
    await page.click('#send-btn');
    await expect(page.locator('.message--send-failed')).toBeVisible({ timeout: 20000 });

    // Reload: the deep-link hash restores the conversation, the unconfirmed
    // send is reconciled back in and - fresh, connection back - resent
    // (Nov 16 2026). page.route blocks persist across reloads: lift them
    await restoreSends(page);
    await page.reload();
    await expect(page.locator('.message.assistant')).toContainText('mock response', {
      timeout: 20000,
    });
    await expect(page.locator('.message--send-failed')).toHaveCount(0);
    await expect(page.locator('.message.user')).toHaveCount(1);
    await expect(page.locator('.toast-info')).toContainText('Resent 1 message.');
  });

  test('the automatic resend after a reload carries a large attachment', async ({ page }) => {
    // ~1.7 MB: over the outbox's localStorage cap (2M base64 chars), so the
    // file only survives the reload in IndexedDB
    const csv = Buffer.from('id,value\n' + '1,abcdefghij\n'.repeat(140_000));
    await page.locator('#file-input').setInputFiles({ name: 'big.csv', mimeType: 'text/csv', buffer: csv });
    await page.waitForSelector('.file-preview', { timeout: 5000 });

    await blockSends(page);
    await page.fill('#message-input', 'Big file after a reload');
    await page.click('#send-btn');
    await expect(page.locator('.message--send-failed')).toBeVisible({ timeout: 20000 });

    await restoreSends(page);
    const resent = page.waitForRequest(CHAT_ENDPOINTS, { timeout: 30000 });
    await page.reload();
    const body = (await resent).postDataJSON() as { files?: Array<{ name: string; data: string }> };
    expect(body.files?.map((f) => f.name)).toEqual(['big.csv']);
    expect(body.files?.[0]?.data.length).toBeGreaterThan(2_000_000);
    await expect(page.locator('.message.assistant')).toContainText('mock response', { timeout: 20000 });
  });

  test('a send that failed offline goes once the connection returns', async ({ page, context }) => {
    // A saved chat first (a new chat's first send also creates it)
    await page.fill('#message-input', 'Hello first');
    await page.click('#send-btn');
    await expect(page.locator('.message.assistant')).toContainText('mock response', { timeout: 20000 });
    // The reply's text shows before its stream ends: send only once the button is Send again
    await expect(page.locator('#send-btn')).toHaveClass(/btn-send/, { timeout: 20000 });

    await context.setOffline(true);
    await page.fill('#message-input', 'Sent from a tunnel');
    await page.click('#send-btn');
    await expect(page.locator('.message.user.message--send-failed')).toBeVisible({ timeout: 20000 });

    await context.setOffline(false); // fires the browser's online event
    await expect(page.locator('.message.assistant')).toHaveCount(2, { timeout: 20000 });
    await expect(page.locator('.message.assistant').last()).toContainText('mock response', {
      timeout: 20000,
    });
    await expect(page.locator('.message--send-failed')).toHaveCount(0);
    await expect(page.locator('.message.user')).toHaveCount(2);
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
    await appReady(page);
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
    await page.waitForTimeout(800); // inside the auto-retry window: still pending, not failed
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

test.describe('Chat - Send Failure Handling on a phone', () => {
  // The resend matters most on an iPhone (the connection drops in tunnels and
  // in the background): same flow at a phone viewport, under the 768 px
  // breakpoint (set after New chat, which lives in the closed sidebar there)
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await appReady(page);
    await page.click('#new-chat-btn');
    await enableStreaming(page);
    await page.setViewportSize({ width: 390, height: 844 });
  });

  test('a send that failed offline goes once the connection returns', async ({ page, context }) => {
    await page.fill('#message-input', 'Hello first');
    await page.click('#send-btn');
    await expect(page.locator('.message.assistant')).toContainText('mock response', { timeout: 20000 });
    // The reply's text shows before its stream ends: send only once the button is Send again
    await expect(page.locator('#send-btn')).toHaveClass(/btn-send/, { timeout: 20000 });

    await context.setOffline(true);
    await page.fill('#message-input', 'Sent from a tunnel');
    await page.click('#send-btn');
    await expect(page.locator('.message.user.message--send-failed')).toBeVisible({ timeout: 20000 });

    await context.setOffline(false);
    await expect(page.locator('.message.assistant')).toHaveCount(2, { timeout: 20000 });
    await expect(page.locator('.message--send-failed')).toHaveCount(0);
    await expect(page.locator('.toast-info')).toContainText('Resent 1 message.');
  });
});
