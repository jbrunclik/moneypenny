/**
 * E2E tests for regenerate / continue / edit-and-resend (the
 * truncate-and-rerun family).
 */
import { test, expect, disableStreaming, setMockResponse, clearMockResponse } from './fixtures';
import { appReady } from '../waits';

test.describe('Chat - Regenerate / Continue / Edit', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await appReady(page);
    await page.click('#new-chat-btn');
    await disableStreaming(page);

    await setMockResponse(page, 'First answer');
    await page.fill('#message-input', 'Original question');
    await page.click('#send-btn');
    await expect(page.locator('.message.assistant')).toContainText('First answer', {
      timeout: 20000,
    });
  });

  test.afterEach(async ({ page }) => {
    await clearMockResponse(page);
  });

  test('regenerate replaces the last assistant response', async ({ page }) => {
    await setMockResponse(page, 'Second answer');
    await page.click('.message.assistant .message-regenerate-btn');

    await expect(page.locator('.message.assistant')).toContainText('Second answer', {
      timeout: 20000,
    });
    // Replaced, not appended - and no duplicate user message
    await expect(page.locator('.message.assistant')).toHaveCount(1);
    await expect(page.locator('.message.user')).toHaveCount(1);
    await expect(page.locator('#messages')).not.toContainText('First answer');
  });

  test('continue appends a follow-on assistant response', async ({ page }) => {
    await setMockResponse(page, 'and the rest of it');
    await page.click('.message.assistant .message-continue-btn');

    await expect(page.locator('.message.assistant')).toHaveCount(2, { timeout: 20000 });
    await expect(page.locator('.message.assistant').last()).toContainText('and the rest of it');
    // The original response stays; no new user message appears
    await expect(page.locator('#messages')).toContainText('First answer');
    await expect(page.locator('.message.user')).toHaveCount(1);
  });

  test('edit-and-resend replaces the tail with the edited turn', async ({ page }) => {
    await setMockResponse(page, 'Answer to the edit');
    await page.click('.message.user .message-edit-btn');

    const textarea = page.locator('.message-edit-textarea');
    await expect(textarea).toBeVisible();
    await expect(textarea).toHaveValue('Original question');
    await textarea.fill('Edited question');
    await page.click('.message-edit-save');

    await expect(page.locator('.message.user')).toContainText('Edited question', {
      timeout: 20000,
    });
    await expect(page.locator('.message.assistant')).toContainText('Answer to the edit', {
      timeout: 20000,
    });
    await expect(page.locator('.message.user')).toHaveCount(1);
    await expect(page.locator('.message.assistant')).toHaveCount(1);
    await expect(page.locator('#messages')).not.toContainText('Original question');

    // Survives a reload - the truncation happened server-side
    await page.reload();
    await expect(page.locator('.message.user')).toContainText('Edited question', {
      timeout: 20000,
    });
    await expect(page.locator('#messages')).not.toContainText('Original question');
  });

  test('edits a message with an attachment in place, keeping the file', async ({ page }) => {
    // Nov 17 2026: such messages could not be edited (resending sent only the
    // text, and the truncation deleted the file)
    await page.click('#new-chat-btn');
    await setMockResponse(page, 'A one-pixel image.');
    await page.locator('#file-input').setInputFiles({
      name: 'pixel.png',
      mimeType: 'image/png',
      buffer: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
        'base64'
      ),
    });
    await page.waitForSelector('.file-preview', { timeout: 5000 });
    await page.fill('#message-input', 'What is this?');
    await page.click('#send-btn');
    await expect(page.locator('.message.assistant')).toContainText('A one-pixel image.', { timeout: 20000 });

    await setMockResponse(page, 'Its colour is black.');
    await page.click('.message.user .message-edit-btn');
    await page.locator('.message-edit-textarea').fill('What colour is it?');
    await page.click('.message-edit-save');

    await expect(page.locator('.message.assistant')).toContainText('Its colour is black.', { timeout: 20000 });
    await expect(page.locator('.message.user')).toHaveCount(1);
    await expect(page.locator('.message.user')).toContainText('What colour is it?');
    await expect(page.locator('.message.user .message-files')).toHaveCount(1);

    // Server-side: the edited text and the file survive a reload
    await page.reload();
    await expect(page.locator('.message.user')).toContainText('What colour is it?', { timeout: 20000 });
    await expect(page.locator('.message.user .message-files')).toHaveCount(1);
    await expect(page.locator('#messages')).not.toContainText('A one-pixel image.');
  });

  test('regenerate buttons only appear on the last assistant message', async ({ page }) => {
    // Add a second turn
    await setMockResponse(page, 'Second turn answer');
    await page.fill('#message-input', 'Second question');
    await page.click('#send-btn');
    await expect(page.locator('.message.assistant')).toHaveCount(2, { timeout: 20000 });

    const first = page.locator('.message.assistant').first();
    const last = page.locator('.message.assistant').last();
    await expect(first.locator('.message-regenerate-btn')).toBeHidden();
    await expect(last.locator('.message-regenerate-btn')).toBeAttached();
  });
});
