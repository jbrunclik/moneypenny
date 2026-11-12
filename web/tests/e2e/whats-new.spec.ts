/**
 * What's new: the read-only announcements chat opens like any chat, shows
 * its announcement as a release card and has no composer (desktop and mobile).
 */
import { test, expect } from '../global-setup';
import { appReady } from './waits';

for (const viewport of [
  { name: 'desktop', width: 1280, height: 800 },
  { name: 'mobile', width: 375, height: 667 },
]) {
  test.describe(`What's new (${viewport.name})`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    test('opens without a composer', async ({ page }) => {
      const seed = await page.request.post('/test/seed-whats-new');
      const { conversation_id: conversationId } = (await seed.json()) as { conversation_id: string };

      await page.goto(`/#/conversations/${conversationId}`);
      await appReady(page);

      const post = page.locator('.message.message--release').last();
      await expect(post).toContainText('Agenty teď založíte');
      // A release card: dated header, section tiles, footer - no chat avatar
      await expect(post.locator('.release-card-date')).toHaveText(/\d{4}/);
      await expect(post.locator('.release-card-section')).toHaveCount(2);
      await expect(post.locator('.release-card-footer')).toContainText('jen pro čtení');
      await expect(post.locator('.message-avatar')).toHaveCount(0);
      await expect(page.locator('.input-area')).toBeHidden();
      await expect(page.locator('.message-regenerate-btn')).toBeHidden();

      // A new chat afterwards has its composer back (the button is in the
      // sidebar, open on desktop)
      if (viewport.name === 'desktop') {
        await page.locator('#new-chat-btn').click();
        await expect(page.locator('.input-area')).toBeVisible();
        // ...at its full height: sized while still hidden it measured 0 and
        // stayed a sliver that scrolls its own placeholder (Nov 2026)
        const fits = await page
          .locator('#message-input')
          .evaluate((el: HTMLTextAreaElement) => el.scrollHeight <= el.clientHeight);
        expect(fits).toBe(true);
      }
    });
  });
}
