/**
 * E2E: keyboard shortcuts on desktop - new chat, chat search, the composer.
 */
import { test, expect } from '../global-setup';
import { appReady } from './waits';

test.describe('keyboard shortcuts', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('⌘K searches, Shift+Esc returns to the composer, ⌘⇧O starts a chat', async ({ page }) => {
    await page.goto('/');
    await appReady(page);

    await page.locator('#message-input').focus();
    await page.keyboard.press('ControlOrMeta+k');
    await expect(page.locator('#search-input')).toBeFocused();

    await page.keyboard.press('Shift+Escape');
    await expect(page.locator('#message-input')).toBeFocused();

    await page.fill('#message-input', 'Hello');
    await page.click('#send-btn');
    await expect(page).toHaveURL(/#\/conversations\//);
    await page.keyboard.press('ControlOrMeta+Shift+o');
    await expect(page.locator('#messages .message')).toHaveCount(0);
    await expect(page).not.toHaveURL(/#\/conversations\//);
  });

  test('⌘K, type, arrows and Enter open a search result', async ({ page }) => {
    const seeded = await page.request.post('/test/seed', {
      data: {
        conversations: ['Wallbox quote', 'Wallbox install'].map((title) => ({
          title,
          messages: [
            { role: 'user', content: `${title} details` },
            { role: 'assistant', content: 'Noted.' },
          ],
        })),
      },
    });
    expect(seeded.ok()).toBeTruthy();
    await page.goto('/');
    await appReady(page);

    await page.keyboard.press('ControlOrMeta+k');
    await page.keyboard.type('wallbox');
    const items = page.locator('.search-result-item');
    await expect(items.first()).toBeVisible();
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowDown');
    await expect(items.nth(1)).toHaveClass(/keyboard-selected/);
    const convId = await items.nth(1).getAttribute('data-conv-id');
    await page.keyboard.press('Enter');

    await expect(page).toHaveURL(new RegExp(`#/conversations/${convId}`));
  });
});
