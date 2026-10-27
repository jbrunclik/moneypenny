/**
 * E2E tests for the composer draft across conversation switches
 */
import type { Page } from '@playwright/test';
import { test, expect } from './fixtures';
import { appReady } from '../waits';

async function startConversation(page: Page, text: string): Promise<string> {
  await page.click('#new-chat-btn');
  await page.fill('#message-input', text);
  await page.click('#send-btn');
  await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 15000 });
  await expect(page).toHaveURL(/#\/conversations\/[0-9a-f-]{36}/);
  return page.url().split('/').pop()!;
}

test.describe('Chat - Composer draft', () => {
  test('text typed while a conversation loads is kept and can be sent', async ({ page }) => {
    await page.goto('/');
    await appReady(page);
    const first = await startConversation(page, 'First conversation');
    const second = await startConversation(page, 'Second conversation');

    // Hold the first conversation's load until the user has typed
    let release!: () => void;
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route(`**/api/conversations/${first}?*`, async (route) => {
      await held;
      await route.continue();
    });
    await page.route(`**/api/conversations/${first}`, async (route) => {
      await held;
      await route.continue();
    });

    await page.locator(`.conversation-item-wrapper[data-conv-id="${first}"] .conversation-item`).click();
    await page.locator('#message-input').pressSequentially('typed while loading');
    // Past the draft-save debounce, so the draft has been saved somewhere
    await page.waitForTimeout(500); // past DRAFT_SAVE_DEBOUNCE_MS (300): the draft has been saved
    release();

    await expect(page.locator('.message.user').first()).toContainText('First conversation', { timeout: 10000 });
    await expect(page.locator('#message-input')).toHaveValue('typed while loading');
    await expect(page.locator('#send-btn')).toBeEnabled();

    // The text belongs to the conversation it was typed into, not the one left
    await page.locator(`.conversation-item-wrapper[data-conv-id="${second}"] .conversation-item`).click();
    await expect(page.locator('.message.user').first()).toContainText('Second conversation', { timeout: 10000 });
    await expect(page.locator('#message-input')).toHaveValue('');
  });
});
