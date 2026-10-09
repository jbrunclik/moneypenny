/**
 * E2E tests for mobile bottom sheets: swipe-down-to-dismiss and staying
 * above the keyboard.
 */
import type { Page } from '@playwright/test';
import { test, expect } from '../global-setup';

test.use({ viewport: { width: 375, height: 812 } });

/** Open the rename prompt (a confirm-style sheet with an input). */
async function openRenamePrompt(page: Page): Promise<void> {
  await page.goto('/');
  await page.waitForSelector('#menu-btn');
  await page.click('#menu-btn');
  await page.click('#new-chat-btn');
  await page.fill('#message-input', 'Sheet test');
  await page.click('#send-btn');
  await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 15000 });
  await page.click('#menu-btn');
  await page.locator('.conversation-item-wrapper').first().hover();
  await page.locator('[data-rename-id]').first().click({ force: true });
  await expect(page.locator('.modal-container:not(.modal-hidden) .modal')).toBeVisible();
}

/** Drag a finger from `fromY` (relative to the sheet's top) down by `dy`. */
async function dragSheet(page: Page, selector: string, fromY: number, dy: number): Promise<void> {
  await page.evaluate(
    ({ selector, fromY, dy }) => {
      const sheet = document.querySelector<HTMLElement>(selector)!;
      const rect = sheet.getBoundingClientRect();
      const x = rect.left + rect.width / 2;
      const y0 = rect.top + fromY;
      // WebKit has no Touch constructor: a plain event carrying the touch
      // list is all the sheet handler reads (touches[0].clientY, timeStamp)
      const fire = (type: string, y: number): void => {
        const event = new Event(type, { bubbles: true, cancelable: true });
        const touches = type === 'touchend' ? [] : [{ identifier: 1, target: sheet, clientX: x, clientY: y }];
        Object.defineProperty(event, 'touches', { value: touches });
        sheet.dispatchEvent(event);
      };
      fire('touchstart', y0);
      for (let i = 1; i <= 5; i++) fire('touchmove', y0 + (dy * i) / 5);
      fire('touchend', y0 + dy);
    },
    { selector, fromY, dy }
  );
}

test('dragging the sheet handle down dismisses a confirm sheet', async ({ page }) => {
  await openRenamePrompt(page);
  await dragSheet(page, '.modal', 10, 300);
  await expect(page.locator('.modal-container')).toHaveClass(/modal-hidden/);
});

test('a drag starting in the sheet body does not dismiss it', async ({ page }) => {
  await openRenamePrompt(page);
  // Below the grab zone: the body's own content keeps its gestures
  const height = await page.locator('.modal').evaluate((el) => el.getBoundingClientRect().height);
  await dragSheet(page, '.modal', height - 20, 300);
  await expect(page.locator('.modal-container')).not.toHaveClass(/modal-hidden/);
});

test('a prompt sheet sits above the keyboard', async ({ page }) => {
  await openRenamePrompt(page);
  // What core/keyboard-viewport.ts sets while the iOS keyboard is open
  await page.evaluate(() => {
    document.documentElement.style.setProperty('--keyboard-inset', '340px');
    document.documentElement.classList.add('kb-open');
  });
  const box = await page.locator('.modal').boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y + box!.height).toBeLessThanOrEqual(812 - 340);
});
