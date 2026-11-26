/**
 * A reply the backup model wrote says so, for good: live while it streams,
 * after a reload, and Retry re-runs the turn on the chat's own model
 * (Nov 26 2026: Carbon was down 20+ minutes and a toast was all that showed).
 */
import { test, expect, enableStreaming, clearMockResponse, resetStreamDelay } from './fixtures';
import { appReady } from '../waits';

const NOTE = '.message.assistant .message-model-fallback';

test.describe('Chat - model fallback note', () => {
  test.beforeEach(async ({ page }) => {
    await clearMockResponse(page);
    await resetStreamDelay(page);
    await page.goto('/');
    await appReady(page);
    await page.click('#new-chat-btn');
    await enableStreaming(page);
  });

  test('marks the reply, survives a reload, and Retry answers on the chat model', async ({
    page,
  }) => {
    await page.request.post('/test/set-model-fallback', { data: { model: 'gemini-4-carbon' } });

    await page.fill('#message-input', 'Hello fallback');
    await page.click('#send-btn');

    const note = page.locator(NOTE);
    await expect(note).toHaveText(/Fast wasn't responding, so Advanced answered instead\./);
    await expect(page.locator('.message.assistant')).toContainText('Hello fallback');
    await expect(page.locator('.message.assistant.streaming')).toHaveCount(0);
    // Above the actions, with Retry on this latest reply
    await expect(note.locator('+ .message-actions')).toHaveCount(1);
    await expect(note.getByRole('button', { name: 'Retry' })).toBeVisible();

    await page.reload();
    await appReady(page);
    await expect(page.locator(NOTE)).toHaveText(/Fast wasn't responding/);

    // The fake falls back once: the re-run is the chat's own model
    await page.locator(NOTE).getByRole('button', { name: 'Retry' }).click();
    await expect(page.locator('.message.assistant')).toHaveCount(1);
    await expect(page.locator('.message.assistant')).toContainText('Hello fallback');
    await expect(page.locator(NOTE)).toHaveCount(0);
  });

  test('a reply from the chat model has no note', async ({ page }) => {
    await page.fill('#message-input', 'Hello plain');
    await page.click('#send-btn');

    await expect(page.locator('.message.assistant')).toContainText('Hello plain');
    await expect(page.locator('.message.assistant.streaming')).toHaveCount(0);
    await expect(page.locator(NOTE)).toHaveCount(0);
  });

  test('Retry shows only on the latest reply', async ({ page }) => {
    await page.request.post('/test/set-model-fallback', { data: { model: 'gemini-4-carbon' } });
    await page.fill('#message-input', 'First question');
    await page.click('#send-btn');
    await expect(page.locator(NOTE)).toHaveCount(1);
    await expect(page.locator('.message.assistant.streaming')).toHaveCount(0);

    await page.fill('#message-input', 'Second question');
    await page.click('#send-btn');
    await expect(page.locator('.message.assistant')).toHaveCount(2);
    await expect(page.locator('.message.assistant.streaming')).toHaveCount(0);

    await expect(page.locator(NOTE)).toHaveCount(1);
    await expect(page.locator(NOTE).getByRole('button', { name: 'Retry' })).toBeHidden();
  });
});
