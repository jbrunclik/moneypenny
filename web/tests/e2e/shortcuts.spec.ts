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
});
