/**
 * Visual regression: chip row, composer mode, slash menu, editor.
 */
import { test, expect } from '../global-setup';

const PROGRAMS = [
  {
    id: 'pushups',
    name: 'Push-ups',
    emoji: '💪',
    created_at: '2026-01-01T00:00:00',
    quick_actions: [
      { id: 'plan', emoji: '📋', label: 'Plan today', body: 'Plan.', fields: [] },
      { id: 'log', emoji: '📊', label: 'Log & review', body: 'Log.', fields: ['Hang time (s)', 'RPE'] },
    ],
  },
];

async function open(page: import('@playwright/test').Page): Promise<void> {
  await page.request.post('/test/set-sports-programs', { data: { programs: PROGRAMS } });
  await page.goto('/#/sports/pushups');
  await page.waitForSelector('.quick-action-chip');
  await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 15000 });
  await page.waitForTimeout(300);
}

test.describe('Visual: Quick actions', () => {
  test('chip row inside the composer', async ({ page }) => {
    await open(page);
    await expect(page.locator('.input-area')).toHaveScreenshot('quick-actions-bar.png');
  });

  test('composer mode', async ({ page }) => {
    await open(page);
    await page.locator('.quick-action-chip').nth(1).click();
    await page.locator('#quick-action-mode .qa-mode-field-input').nth(0).fill('54');
    await page.waitForTimeout(200);
    await expect(page.locator('.input-area')).toHaveScreenshot('quick-actions-composer-mode.png');
  });

  test('slash menu', async ({ page }) => {
    await open(page);
    await page.fill('#message-input', '/');
    await page.waitForTimeout(200);
    await expect(page.locator('.input-area')).toHaveScreenshot('quick-actions-slash-menu.png');
  });

  test('editor list', async ({ page }) => {
    await open(page);
    await page.locator('.program-quick-actions-btn').click();
    await page.waitForTimeout(200);
    await expect(page.locator('.qa-editor')).toHaveScreenshot('quick-actions-editor.png');
  });
});

test.describe('Visual: Quick actions mobile', () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test('chip row and composer mode', async ({ page }) => {
    await open(page);
    await expect(page.locator('.input-area')).toHaveScreenshot('quick-actions-bar-mobile.png');
    await page.locator('.quick-action-chip').nth(1).click();
    await page.waitForTimeout(250);
    await expect(page.locator('.input-area')).toHaveScreenshot('quick-actions-composer-mode-mobile.png');
  });

  test('editor detail form', async ({ page }) => {
    await open(page);
    await page.locator('.quick-action-edit-chip').click();
    await page.locator('.qa-editor-edit').first().click();
    await page.waitForTimeout(200);
    await expect(page.locator('.qa-editor')).toHaveScreenshot('quick-actions-editor-detail-mobile.png');
  });
});
