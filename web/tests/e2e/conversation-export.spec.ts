/**
 * Export a conversation as Markdown: the chat header's icon on desktop, the
 * conversation's action sheet on mobile. The file holds the title and the
 * messages as written.
 */
import { readFileSync } from 'fs';
import type { Download, Page } from '@playwright/test';
import { test, expect } from '../global-setup';
import { appReady } from './waits';

async function chatWithOneTurn(page: Page): Promise<void> {
  await page.goto('/');
  await appReady(page);
  if (await page.locator('#menu-btn').isVisible()) await page.click('#menu-btn');
  await page.click('#new-chat-btn');
  await page.fill('#message-input', 'Export me please');
  await page.click('#send-btn');
  await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 15000 });
}

function contents(download: Download): Promise<string> {
  return download.path().then((path) => readFileSync(path, 'utf8'));
}

test.describe('Export a conversation', () => {
  test('the chat header downloads it as Markdown', async ({ page }) => {
    await chatWithOneTurn(page);
    // A brand-new chat keeps its plain header until reopened (its actions too)
    await page.reload();
    await appReady(page);
    await page.locator('.conversation-item').first().click();
    const exportButton = page.locator('#chat-header [aria-label="Export as Markdown"]');
    await expect(exportButton).toBeVisible();

    const [download] = await Promise.all([page.waitForEvent('download'), exportButton.click()]);

    expect(download.suggestedFilename()).toMatch(/\.md$/);
    const text = await contents(download);
    expect(text).toMatch(/^# /);
    expect(text).toContain('**You**');
    expect(text).toContain('Export me please');
  });
});

test.describe('Export a conversation on mobile', () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test('the conversation action sheet offers the export', async ({ page }) => {
    await chatWithOneTurn(page);
    await page.click('#menu-btn');
    // The "more" button shows on touch screens only; the sidebar handles its
    // click by delegation, so it is triggered here as a tap would
    await page.locator('[data-more-id]').first().evaluate((el) => (el as HTMLElement).click());

    const item = page.locator('.action-sheet-item', { hasText: 'Export as Markdown' });
    await expect(item).toBeVisible();
    const [download] = await Promise.all([page.waitForEvent('download'), item.click()]);

    expect(await contents(download)).toContain('Export me please');
  });
});
