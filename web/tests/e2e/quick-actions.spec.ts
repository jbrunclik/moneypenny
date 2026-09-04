/**
 * E2E: program quick actions (chip bar, field form, editor, save-from-message).
 */
import { test, expect } from '../global-setup';

const PROGRAMS = [
  {
    id: 'pushups',
    name: 'Push-ups',
    emoji: '💪',
    created_at: '2026-01-01T00:00:00',
    quick_actions: [
      { id: 'plan', emoji: '📋', label: 'Plan today', body: 'Plan my session please.', fields: [] },
      {
        id: 'log',
        emoji: '📊',
        label: 'Log & review',
        body: 'Review my session.',
        fields: ['Hang time (s)', 'Comments'],
      },
    ],
  },
];

async function openProgram(page: import('@playwright/test').Page): Promise<void> {
  await page.request.post('/test/set-sports-programs', { data: { programs: PROGRAMS } });
  await page.goto('/#/sports/pushups');
  // The program header is hidden on mobile; the bar exists in both layouts
  await page.waitForSelector('#quick-actions-bar .quick-action-edit-chip');
  // The auto session-start message gets a mock reply; wait for it to finish
  await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 15000 });
}

test.describe('Quick actions - desktop', () => {
  test('bar shows chips and a no-field chip sends its body', async ({ page }) => {
    await openProgram(page);
    const chips = page.locator('.quick-action-chip');
    await expect(chips).toHaveCount(2);
    await chips.nth(0).click();
    await expect(page.locator('.message.user').last()).toContainText('Plan my session please.');
    await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 15000 });
  });

  test('a field chip opens the form and sends Label: value lines', async ({ page }) => {
    await openProgram(page);
    await page.locator('.quick-action-chip').nth(1).click();
    const form = page.locator('.quick-action-form');
    await expect(form).toBeVisible();
    await form.locator('textarea').nth(0).fill('54');
    await form.locator('textarea').nth(1).fill('felt strong');
    await form.locator('.quick-action-form-send').click();
    const last = page.locator('.message.user').last();
    await expect(last).toContainText('Review my session.');
    await expect(last).toContainText('Hang time (s): 54');
    await expect(last).toContainText('Comments: felt strong');
  });

  test('editor adds an action that appears as a chip and persists', async ({ page }) => {
    await openProgram(page);
    await page.locator('.program-quick-actions-btn').click();
    await page.locator('.qa-editor-add').click();
    await page.fill('.qa-detail-label', 'Week overview');
    await page.fill('.qa-detail-body', 'Summarize the week.');
    await page.locator('.qa-detail-done').click();
    await page.locator('.qa-editor-save').click();
    await expect(page.locator('.quick-action-chip')).toHaveCount(3);
    await expect(page.locator('.quick-action-chip').nth(2)).toContainText('Week overview');
    await page.reload();
    await page.waitForSelector('#quick-actions-bar .quick-action-edit-chip');
    await expect(page.locator('.quick-action-chip')).toHaveCount(3);
  });

  test('save as quick action prefills the editor with the message', async ({ page }) => {
    await openProgram(page);
    await page.fill('#message-input', 'Business as usual please');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 15000 });
    const userMsg = page.locator('.message.user').last();
    await userMsg.hover();
    await userMsg.locator('.message-save-quick-action-btn').click({ force: true });
    await expect(page.locator('.qa-detail-body')).toHaveValue('Business as usual please');
  });

  test('bar is absent in a normal conversation', async ({ page }) => {
    await openProgram(page);
    await page.locator('.chat-header-back').click();
    await page.click('#new-chat-btn');
    await expect(page.locator('#quick-actions-bar')).toBeHidden();
  });
});

test.describe('Quick actions - mobile', () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test('bar hides while typing and returns when the composer is cleared', async ({ page }) => {
    await openProgram(page);
    const bar = page.locator('#quick-actions-bar');
    await expect(bar).toBeVisible();
    await page.fill('#message-input', 'typing…');
    await expect(bar).toBeHidden();
    await page.fill('#message-input', '');
    await expect(bar).toBeVisible();
  });

  test('gear chip opens the editor on mobile', async ({ page }) => {
    await openProgram(page);
    await page.locator('.quick-action-edit-chip').click();
    await expect(page.locator('.qa-editor')).toBeVisible();
    await expect(page.locator('.qa-editor-row')).toHaveCount(2);
  });

  test('field form opens as a bottom sheet and sends', async ({ page }) => {
    await openProgram(page);
    await page.locator('.quick-action-chip').nth(1).click();
    const form = page.locator('.quick-action-form');
    await expect(form).toBeVisible();
    const box = await form.boundingBox();
    expect(box!.y + box!.height).toBeGreaterThan(800); // pinned to the bottom
    await form.locator('textarea').nth(0).fill('60');
    await form.locator('.quick-action-form-send').click();
    await expect(page.locator('.message.user').last()).toContainText('Hang time (s): 60');
  });
});
