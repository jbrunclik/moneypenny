/**
 * Visual regression tests for projects: a project's page (chats,
 * instructions, project memory) and the sidebar's Projects group.
 */
import type { Page } from '@playwright/test';
import { test, expect } from '../global-setup';
import { pageSettled } from '../e2e/waits';

async function seedProject(page: Page): Promise<string> {
  const created = await page.request.post('/api/projects', {
    data: { name: 'Bikes', instructions: 'Metric units and Czech shops. Prefer Shimano GRX parts.' },
  });
  const { id } = (await created.json()) as { id: string };
  await page.request.post('/api/projects', { data: { name: 'Home' } });
  for (const title of ['Canyon Grizl setup', 'Gravel tyres for winter']) {
    const conv = await page.request.post('/api/conversations', { data: { project_id: id } });
    const { id: convId } = (await conv.json()) as { id: string };
    await page.request.patch(`/api/conversations/${convId}`, { data: { title } });
  }
  for (const content of ['Rides a Canyon Grizl CF SL 7, size M', 'Tubeless on both bikes since 2025']) {
    await page.request.post('/test/seed-project-memory', { data: { project_id: id, content } });
  }
  return id;
}

async function openProject(page: Page): Promise<void> {
  const id = await seedProject(page);
  await page.goto(`/#/projects/${id}`);
  await page.waitForSelector('.project-page .project-chat-list [data-conv-id]');
  await pageSettled(page);
}

test.describe('Visual: Project page - Desktop', () => {
  test('project page with chats, instructions and memory', async ({ page }) => {
    await openProject(page);
    await expect(page.locator('.main')).toHaveScreenshot('project-page.png');
  });

  test('a hovered chat row shows its actions, Move to project among them', async ({ page }) => {
    const conv = await page.request.post('/api/conversations', { data: {} });
    const { id } = (await conv.json()) as { id: string };
    await page.request.patch(`/api/conversations/${id}`, { data: { title: 'Problémy s kůží a vlasy' } });
    await openProject(page);
    const row = page.locator(`#conversations-list [data-conv-id="${id}"] .conversation-item`);
    await row.hover();
    await expect(row.locator('.conversation-actions')).toHaveCSS('opacity', '1');
    await expect(row).toHaveScreenshot('sidebar-row-hover.png');
  });

  test('sidebar with projects', async ({ page }) => {
    await openProject(page);
    await expect(page.locator('#sidebar')).toHaveScreenshot('project-sidebar.png');
  });
});

test.describe('Visual: Project page - Mobile', () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test('project page on mobile', async ({ page }) => {
    await openProject(page);
    await expect(page.locator('.main')).toHaveScreenshot('project-page-mobile.png');
  });
});
