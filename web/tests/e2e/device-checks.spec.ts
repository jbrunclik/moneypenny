/**
 * The guided device check runner end to end (admin page -> Run device checks).
 * Playwright has no software keyboard, so the keyboard steps report
 * "skipped - no software keyboard" without asking for a tap; the rest runs
 * for real on the fixture conversation and lands in the admin history.
 */
import type { Page } from '@playwright/test';
import { test, expect } from '../global-setup';

async function seedConversation(page: Page): Promise<string> {
  const response = await page.request.post('/test/seed', {
    data: {
      conversations: [
        { title: 'Kept chat', messages: [{ role: 'user', content: 'Hello' }, { role: 'assistant', content: 'Hi there' }] },
      ],
    },
  });
  expect(response.ok()).toBe(true);
  const body = (await response.json()) as { conversation_ids: string[] };
  const id = body.conversation_ids[0];
  if (!id) throw new Error('seed returned no conversation');
  return id;
}

async function openAdmin(page: Page): Promise<void> {
  const menuButton = page.locator('#menu-btn');
  // Phones keep the user menu in the sidebar
  if (await menuButton.isVisible()) await menuButton.click();
  await page.click('#user-menu-btn');
  await page.click('#admin-btn');
  await expect(page.locator('.admin-page .device-check-section')).toBeVisible();
}

for (const [name, viewport] of [
  ['desktop', { width: 1280, height: 1024 }],
  ['phone', { width: 375, height: 812 }],
] as const) {
  test.describe(`Device checks (${name})`, () => {
    test.use({ viewport });

    test('runs the suite on a fixture, stores the run and puts everything back', async ({ page }) => {
      const keptId = await seedConversation(page);
      await page.goto(`/#/conversations/${keptId}`);
      await expect(page.locator('.message.assistant')).toContainText('Hi there');

      await openAdmin(page);
      await expect(page.locator('.device-check-history')).toContainText('No runs yet');
      await page.click('.device-check-run-btn');
      await expect(page.locator('.admin-page')).toHaveCount(0);

      const card = page.locator('.device-check-card');
      await expect(card.locator('.device-check-close')).toBeVisible({ timeout: 25000 });
      await expect(card.locator('.device-check-live')).toHaveText('3/3 passed, 3 skipped');
      for (const id of ['environment', 'long-conversation', 'send-to-top']) {
        await expect(card.locator(`[data-check-id="${id}"]`)).toHaveAttribute('data-status', 'passed');
      }
      for (const id of ['keyboard-open', 'scroll-button-keyboard', 'keyboard-close']) {
        const row = card.locator(`[data-check-id="${id}"]`);
        await expect(row).toHaveAttribute('data-status', 'skipped');
        await expect(row).toContainText('no software keyboard');
      }
      // Back on the chat that was open, the fixture gone for good
      await expect(page).toHaveURL(new RegExp(`#/conversations/${keptId}$`));
      await expect(page.locator('.message.assistant').last()).toContainText('Hi there');
      const archived = await page.request.get('/api/conversations/archived');
      expect(((await archived.json()) as { conversations: unknown[] }).conversations).toEqual([]);

      // Close returns to the admin page, which lists the run
      await card.locator('.device-check-close').click();
      const run = page.locator('.admin-page .device-check-run');
      await expect(run).toHaveCount(1);
      await expect(run.locator('summary')).toContainText(/\[kb\d+\]/);
      await expect(run.locator('summary')).toContainText('3/3 passed, 3 skipped');
      await expect(run.locator('summary')).toContainText('browser tab');
      await run.locator('summary').click();
      await expect(run.locator('.device-check-scenario').first()).toContainText('inner_height');
      await expect(run.locator('.device-check-scenario[data-status="passed"]')).toHaveCount(3);
    });

    test('Stop ends the run without storing it and still removes the fixture', async ({ page }) => {
      await page.goto('/');
      await openAdmin(page);
      await page.click('.device-check-run-btn');
      const card = page.locator('.device-check-card');
      await card.locator('.device-check-stop').click();
      // The open conversation alone settles for longer than this click takes
      await expect(card.locator('.device-check-live')).toHaveText('Stopped - nothing was saved.', { timeout: 25000 });
      const runs = await page.request.get('/api/admin/device-check-runs');
      expect(((await runs.json()) as { runs: unknown[] }).runs).toEqual([]);
      await expect
        .poll(async () => ((await (await page.request.get('/api/conversations/archived')).json()) as { conversations: unknown[] }).conversations)
        .toEqual([]);
    });
  });
}
