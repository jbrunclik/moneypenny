/**
 * Changes made on ANOTHER device reach this one on the regular poll tick.
 *
 * The other device is the API (same user). Every test uses the incremental
 * sync only: the old timestamp sync noticed archive/trash/delete solely on a
 * full sync, which a tab that stays visible never runs - so chats deleted on
 * the phone lingered on the desktop. (The older sync.spec.ts tests forced
 * full syncs and masked that.)
 */
import { test, expect } from '../global-setup';

declare global {
  interface Window {
    __testIncrementalSync: () => Promise<void>;
  }
}

let ids: { alpha: string; beta: string };

test.beforeEach(async ({ page, request }) => {
  const seeded = await request.post('/test/seed', {
    data: {
      conversations: [
        { title: 'Alpha', messages: [{ role: 'user', content: 'a?' }, { role: 'assistant', content: 'a!' }] },
        { title: 'Beta', messages: [{ role: 'user', content: 'b?' }, { role: 'assistant', content: 'b!' }] },
      ],
    },
  });
  const [alpha, beta] = (await seeded.json()).conversation_ids as string[];
  ids = { alpha, beta };
  await page.goto('/');
  await expect(page.locator('.conversation-item-wrapper', { hasText: 'Alpha' })).toBeVisible();
});

const item = (page: import('@playwright/test').Page, title: string) =>
  page.locator('.conversation-item-wrapper', { hasText: title });

async function poll(page: import('@playwright/test').Page): Promise<void> {
  await page.evaluate(() => window.__testIncrementalSync());
}

test('a chat archived on another device leaves the sidebar', async ({ page, request }) => {
  await request.post(`/api/conversations/${ids.alpha}/archive`);
  await poll(page);
  await expect(item(page, 'Alpha')).toHaveCount(0);
  await expect(item(page, 'Beta')).toBeVisible();
});

test('a chat moved to the trash on another device leaves the sidebar', async ({ page, request }) => {
  await request.delete(`/api/conversations/${ids.alpha}`);
  await poll(page);
  await expect(item(page, 'Alpha')).toHaveCount(0);
});

test('a chat deleted for good on another device leaves the sidebar', async ({ page, request }) => {
  await request.delete(`/api/conversations/${ids.alpha}`);
  await request.delete(`/api/conversations/${ids.alpha}/permanent`);
  await poll(page);
  await expect(item(page, 'Alpha')).toHaveCount(0);
});

test('the open chat trashed on another device closes with a notice', async ({ page, request }) => {
  await item(page, 'Alpha').click();
  await expect(page.locator('.message.assistant')).toContainText('a!');

  await request.delete(`/api/conversations/${ids.alpha}`);
  await poll(page);

  await expect(page.locator('.toast')).toContainText('moved to the trash on another device');
  await expect(page.locator('.message.assistant')).toHaveCount(0);
});

test('a chat restored on another device comes back without an unread badge', async ({ page, request }) => {
  await request.delete(`/api/conversations/${ids.alpha}`);
  await poll(page);
  await expect(item(page, 'Alpha')).toHaveCount(0);

  await request.post(`/api/conversations/${ids.alpha}/restore`);
  await poll(page);

  await expect(item(page, 'Alpha')).toBeVisible();
  await expect(item(page, 'Alpha').locator('.unread-badge')).toHaveCount(0);
});

test('a pin on another device moves the chat to Pinned', async ({ page, request }) => {
  await request.post(`/api/conversations/${ids.beta}/pin`);
  await poll(page);
  await expect(page.locator('.conversation-group-label').first()).toHaveText('Pinned');
  await expect(page.locator('.conversation-item-wrapper').first()).toContainText('Beta');
});

test('a rename on another device shows up', async ({ page, request }) => {
  await request.patch(`/api/conversations/${ids.beta}`, { data: { title: 'Beta renamed' } });
  await poll(page);
  await expect(item(page, 'Beta renamed')).toBeVisible();
});
