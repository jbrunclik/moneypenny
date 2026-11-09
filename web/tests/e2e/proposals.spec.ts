/**
 * Proposal cards: a reply's card is approved on its button or by replying
 * "ano" - either way the server stores exactly the card's reminder and the
 * card collapses to the outcome (desktop and mobile).
 */
import { test, expect } from '../global-setup';
import { appReady } from './waits';

for (const viewport of [
  { name: 'desktop', width: 1280, height: 800 },
  { name: 'mobile', width: 375, height: 667 },
]) {
  test.describe(`Proposal cards (${viewport.name})`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    test.beforeEach(async ({ page }) => {
      const seed = await page.request.post('/test/seed-proposal');
      const { conversation_id: conversationId } = (await seed.json()) as { conversation_id: string };
      await page.goto(`/#/conversations/${conversationId}`);
      await appReady(page);
    });

    test('approve on the card sets the reminder', async ({ page }) => {
      const card = page.locator('.proposal-card');
      await expect(card.locator('.proposal-card__summary')).toHaveText('Reminder: "Call the plumber"');
      await expect(card.locator('.proposal-card__row dt')).toHaveText(['When', 'Ends']);

      await card.getByRole('button', { name: 'Set it up' }).click();

      await expect(card).toHaveClass(/proposal-card--approved/);
      await expect(card).toContainText('Reminder set - Fri 13 Nov 2099 08:00, then done.');
      await expect(card.getByRole('button')).toHaveCount(0);
    });

    test('typing ano approves it', async ({ page }) => {
      await page.locator('#message-input').fill('ano');
      await page.locator('#send-btn').click();

      const card = page.locator('.message.assistant').first().locator('.proposal-card');
      await expect(card).toHaveClass(/proposal-card--approved/, { timeout: 15_000 });
    });
  });
}
