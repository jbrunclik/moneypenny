/**
 * E2E: bulk delete from the sidebar (select chats -> move to trash -> Undo),
 * on desktop and mobile.
 */
import type { APIRequestContext, Page } from '@playwright/test';
import { test, expect } from '../global-setup';

const rows = (page: Page) =>
  page.locator('#conversations-list .conversation-item-wrapper[data-conv-id]');
const row = (page: Page, title: string) =>
  page.locator('#conversations-list .conversation-item-wrapper', { hasText: title });

async function seed(request: APIRequestContext, titles: string[]): Promise<string[]> {
  const seeded = await request.post('/test/seed', {
    data: {
      conversations: titles.map((title) => ({
        title,
        messages: [
          { role: 'user', content: `${title}?` },
          { role: 'assistant', content: `${title}!` },
        ],
      })),
    },
  });
  return (await seeded.json()).conversation_ids as string[];
}

for (const viewport of [
  { name: 'desktop', size: { width: 1280, height: 800 } },
  { name: 'mobile', size: { width: 375, height: 812 } },
]) {
  test.describe(`bulk delete (${viewport.name})`, () => {
    test.use({ viewport: viewport.size });

    async function open(page: Page, expectedRows: number): Promise<void> {
      await page.goto('/');
      if (viewport.name === 'mobile') {
        await page.click('#menu-btn');
        await expect(page.locator('#sidebar')).toHaveClass(/open/);
      }
      await expect(rows(page)).toHaveCount(expectedRows);
    }

    async function enterSelection(page: Page): Promise<void> {
      await page.click('#user-menu-btn');
      await page.click('#select-chats-btn');
      await expect(page.locator('#selection-bar')).toBeVisible();
    }

    test('pick three, move to trash, Undo restores them', async ({ page, request }) => {
      await seed(request, ['One', 'Two', 'Three', 'Four']);
      await open(page, 4);

      await enterSelection(page);
      for (const title of ['One', 'Two', 'Three']) await row(page, title).click();
      await expect(page.locator('.selection-count')).toHaveText('3 selected');
      await page.click('#selection-trash');

      await expect(rows(page)).toHaveCount(1);
      await expect(row(page, 'Four')).toBeVisible();
      await expect(page.locator('.modal-container:not(.modal-hidden)')).toHaveCount(0);
      await expect(page.locator('#selection-bar')).toBeHidden();
      await page.getByRole('button', { name: 'Undo' }).click();
      await expect(rows(page)).toHaveCount(4);
    });

    test('select all, untick one: only it and pinned chats remain', async ({ page, request }) => {
      const [pinnedId] = await seed(request, ['Pinned', 'Keep', 'Gone 1', 'Gone 2']);
      expect((await request.post(`/api/conversations/${pinnedId}/pin`)).ok()).toBeTruthy();
      await open(page, 4);

      await enterSelection(page);
      await page.click('#selection-all');
      await row(page, 'Keep').click();
      await expect(page.locator('.selection-count')).toHaveText('2 selected');
      await page.click('#selection-trash');

      await expect(rows(page)).toHaveCount(2);
      await expect(row(page, 'Pinned')).toBeVisible();
      await expect(row(page, 'Keep')).toBeVisible();
    });

    test('Cancel leaves selection mode and rows open again', async ({ page, request }) => {
      await seed(request, ['Solo']);
      await open(page, 1);

      await enterSelection(page);
      await page.click('#selection-cancel');
      await expect(page.locator('#selection-bar')).toBeHidden();
      await row(page, 'Solo').click();
      await expect(page.locator('.message.assistant')).toHaveCount(1);
    });
  });
}
