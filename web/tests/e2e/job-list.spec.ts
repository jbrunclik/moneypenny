/**
 * The Command Center's job list against the real backend (standing chats
 * phase 3): an agent's job and a chat item in one list, pause and resume,
 * run, cancel - on desktop and mobile.
 */
import type { Page } from '@playwright/test';
import { test, expect } from '../global-setup';

async function seedAgent(page: Page, name: string): Promise<string> {
  const response = await page.request.post('/test/seed-agent', { data: { name } });
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as { job_id: string }).job_id;
}

async function seedChatItem(page: Page): Promise<void> {
  const response = await page.request.post('/test/seed', {
    data: {
      conversations: [
        {
          title: "Dog's tail",
          messages: [{ role: 'user', content: 'Check the school job board daily' }],
          scheduled_items: [
            { kind: 'watcher', text: "the school's job board", end_condition: 'a teacher job is posted', interval_hours: 24 },
          ],
        },
      ],
    },
  });
  expect(response.ok()).toBeTruthy();
}

for (const [label, viewport] of [
  ['desktop', { width: 1280, height: 800 }],
  ['mobile', { width: 375, height: 812 }],
] as const) {
  test.describe(`Job list (${label})`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize(viewport);
    });

    test('lists an agent job and a chat item', async ({ page }) => {
      await seedAgent(page, 'Coach');
      await seedChatItem(page);

      await page.goto('/#/agents');

      const rows = page.locator('.job-row');
      await expect(rows).toHaveCount(2);
      await expect(page.locator('.job-row', { hasText: 'Coach' }).locator('.job-run')).toBeVisible();
      const item = page.locator('.job-row', { hasText: "the school's job board" });
      await expect(item.locator('.job-meta')).toContainText("Dog's tail");
      await expect(item.locator('.job-cancel')).toBeVisible();
    });

    test('pauses then resumes an agent job', async ({ page }) => {
      await seedAgent(page, 'Coach');
      await page.goto('/#/agents');
      const row = page.locator('.job-row', { hasText: 'Coach' });

      await row.locator('.job-pause').click();
      await expect(row.locator('.job-status')).toHaveText('paused');

      await row.locator('.job-resume').click();
      await expect(row.locator('.job-status')).toHaveCount(0);
      await expect(row.locator('.job-pause')).toBeVisible();
    });

    test('runs an agent job', async ({ page }) => {
      await seedAgent(page, 'Coach');
      await page.goto('/#/agents');
      const row = page.locator('.job-row', { hasText: 'Coach' });

      await row.locator('.job-run').click();

      await expect(row.locator('.job-runs summary')).toBeVisible();
    });

    test('cancels a chat item', async ({ page }) => {
      await seedChatItem(page);
      await page.goto('/#/agents');

      await page.locator('.job-row', { hasText: "the school's job board" }).locator('.job-cancel').click();

      await expect(page.locator('.jobs-empty')).toBeVisible();
    });
  });
}
