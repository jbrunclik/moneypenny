/**
 * E2E: projects - create one from the user menu, start a chat in it from its
 * page; the chat lives on the project page, not in the main list, and its
 * header links back to the project. Desktop and mobile.
 */
import type { Page } from '@playwright/test';
import { test, expect } from '../global-setup';
import { appReady, serverReplySaved } from './waits';

async function seedChats(page: Page, titles: string[]): Promise<void> {
  const seeded = await page.request.post('/test/seed', {
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
  expect(seeded.ok()).toBeTruthy();
}

for (const viewport of [
  { name: 'desktop', size: { width: 1280, height: 800 } },
  { name: 'mobile', size: { width: 375, height: 812 } },
]) {
  test.describe(`projects (${viewport.name})`, () => {
    test.use({ viewport: viewport.size });

    async function openSidebar(page: Page): Promise<void> {
      if (viewport.name === 'mobile') {
        await page.click('#menu-btn');
        await expect(page.locator('#sidebar')).toHaveClass(/open/);
      }
    }

    test('a chat started on a project page lives in the project', async ({ page }) => {
      await page.goto('/');
      await appReady(page);
      await openSidebar(page);

      await page.click('#user-menu-btn');
      await page.click('#new-project-btn');
      await page.locator('.modal-input').fill('Bikes');
      await page.locator('.modal-confirm').click();

      const projectPage = page.locator('.project-page');
      await expect(projectPage.locator('.project-name')).toHaveText('Bikes');
      await expect(projectPage).toContainText('No chats in this project yet');
      await expect(page).toHaveURL(/#\/projects\//);

      await projectPage.locator('.project-new-chat').click();
      await page.fill('#message-input', 'Which tyres for gravel?');
      await page.click('#send-btn');
      await expect(page).toHaveURL(/#\/conversations\//);
      await serverReplySaved(page);
      // The chat header links back to the project (on mobile, before the title)
      const projectLink = viewport.name === 'desktop' ? '#chat-header .chat-header-project' : '#current-chat-project';
      await expect(page.locator(projectLink)).toBeVisible();
      await expect(page.locator(projectLink)).toHaveText('Bikes');

      // Not in the main list; on the project page instead
      await openSidebar(page);
      await expect(page.locator('#conversations-list [data-conv-id]')).toHaveCount(0);
      const projectRow = page.locator('.project-item', { hasText: 'Bikes' });
      await expect(projectRow).toBeVisible();
      await projectRow.click();
      await expect(page.locator('.project-page .project-chat-list [data-conv-id]')).toHaveCount(1);
    });

    test('an existing chat moves into a project from its menu', async ({ page }) => {
      await seedChats(page, ['Wallbox hookup', 'Dinner ideas']);
      await page.request.post('/api/projects', { data: { name: 'Home' } });
      await page.goto('/');
      await appReady(page);
      await openSidebar(page);

      const row = page.locator('[data-conv-id]', { hasText: 'Wallbox hookup' });
      await row.locator('[data-more-id]').evaluate((el) => (el as HTMLElement).click());
      await page.locator('.action-sheet-item', { hasText: 'Move to project' }).click();
      await page.locator('.action-sheet-item', { hasText: 'Home' }).click();

      await expect(page.locator('#conversations-list [data-conv-id]', { hasText: 'Wallbox hookup' })).toHaveCount(0);
      await expect(page.locator('#conversations-list [data-conv-id]', { hasText: 'Dinner ideas' })).toHaveCount(1);
      await page.locator('.project-item', { hasText: 'Home' }).click();
      await expect(page.locator('.project-page .project-chat-list [data-conv-id]', { hasText: 'Wallbox hookup' })).toBeVisible();
    });

    test('selected chats move into a new project together', async ({ page }) => {
      await seedChats(page, ['Canyon setup', 'GT Grade stripdown', 'Dinner ideas']);
      await page.goto('/');
      await appReady(page);
      await openSidebar(page);

      await page.click('#user-menu-btn');
      await page.click('#select-chats-btn');
      for (const title of ['Canyon setup', 'GT Grade stripdown']) {
        await page.locator('#conversations-list [data-conv-id]', { hasText: title }).click();
      }
      await page.click('#selection-move');
      await page.locator('.action-sheet-item', { hasText: 'New project' }).click();
      await page.locator('.modal-input').fill('Bikes');
      await page.locator('.modal-confirm').click();

      await expect(page.locator('#selection-bar')).toBeHidden();
      await expect(page.locator('#conversations-list [data-conv-id]')).toHaveCount(1);
      await page.locator('.project-item', { hasText: 'Bikes' }).click();
      await expect(page.locator('.project-page .project-chat-list [data-conv-id]')).toHaveCount(2);
    });

    test('the project instructions save on blur', async ({ page }) => {
      const created = await page.request.post('/api/projects', { data: { name: 'Home' } });
      expect(created.ok()).toBeTruthy();
      const { id } = (await created.json()) as { id: string };

      await page.goto(`/#/projects/${id}`);
      await appReady(page);
      const field = page.locator('.project-instructions-input');
      await field.fill('Metric units, prices in CZK');
      await page.locator('.project-name').click();
      await expect(page.locator('.project-instructions-saved')).toHaveText('Saved');

      const detail = await page.request.get(`/api/projects/${id}`);
      expect(((await detail.json()) as { instructions: string }).instructions).toBe('Metric units, prices in CZK');
    });
  });
}
