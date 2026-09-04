/**
 * E2E: program quick actions (chip row, composer mode, slash menu, editor,
 * save-from-message).
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
        fields: ['Hang time (s)', 'RPE'],
      },
    ],
  },
];

async function openProgram(page: import('@playwright/test').Page): Promise<void> {
  await page.request.post('/test/set-sports-programs', { data: { programs: PROGRAMS } });
  await page.goto('/#/sports/pushups');
  // The program header is hidden on mobile; the chip row exists in both layouts
  await page.waitForSelector('#quick-actions-bar .quick-action-edit-chip');
  // The auto session-start message gets a mock reply; wait for it to finish
  await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 15000 });
}

test.describe('Quick actions - desktop', () => {
  test('a chip without questions still opens composer mode with the cursor in the note', async ({ page }) => {
    await openProgram(page);
    await expect(page.locator('#input-container #quick-actions-bar .quick-action-chip')).toHaveCount(2);
    await page.locator('.quick-action-chip').nth(0).click();
    const mode = page.locator('#quick-action-mode');
    await expect(mode).toBeVisible();
    await expect(mode.locator('.qa-mode-field-input')).toHaveCount(0);
    await expect(page.locator('#message-input')).toBeFocused();
    await expect(page.locator('#send-btn')).toBeEnabled();
    await page.fill('#message-input', 'legs are sore');
    await page.click('#send-btn');
    const last = page.locator('.message.user').last();
    await expect(last).toContainText('Plan my session please.');
    await expect(last).toContainText('legs are sore');
    await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 15000 });
  });

  test('a chip without questions sends just its body when the note is left empty', async ({ page }) => {
    await openProgram(page);
    await page.locator('.quick-action-chip').nth(0).click();
    await page.click('#send-btn');
    await expect(page.locator('.message.user .message-content').last()).toHaveText('Plan my session please.');
  });

  test('a chip with questions enters composer mode; answers + note are sent as one message', async ({ page }) => {
    await openProgram(page);
    await page.locator('.quick-action-chip').nth(1).click();
    const mode = page.locator('#quick-action-mode');
    await expect(mode).toBeVisible();
    await expect(mode.locator('.qa-mode-label')).toHaveText('Log & review');
    await expect(page.locator('#quick-actions-bar')).toBeHidden();
    await expect(page.locator('#send-btn')).toBeEnabled();
    await expect(mode.locator('.qa-mode-field-input').nth(0)).toBeFocused();
    await mode.locator('.qa-mode-field-input').nth(0).fill('54');
    await mode.locator('.qa-mode-field-input').nth(1).fill('8');
    await page.fill('#message-input', 'felt strong');
    await page.click('#send-btn');
    const last = page.locator('.message.user').last();
    await expect(last).toContainText('Review my session.');
    await expect(last).toContainText('Hang time (s): 54');
    await expect(last).toContainText('RPE: 8');
    await expect(last).toContainText('felt strong');
    // Composer is back to normal
    await expect(mode).toBeHidden();
    await expect(page.locator('#quick-actions-bar')).toBeVisible();
    await expect(page.locator('#message-input')).toHaveAttribute('placeholder', 'Type your message...');
  });

  test('Enter in the last question sends on desktop', async ({ page }) => {
    await openProgram(page);
    await page.locator('.quick-action-chip').nth(1).click();
    const inputs = page.locator('#quick-action-mode .qa-mode-field-input');
    await inputs.nth(0).fill('60');
    await inputs.nth(0).press('Enter');
    await expect(inputs.nth(1)).toBeFocused();
    await inputs.nth(1).press('Enter');
    await expect(page.locator('.message.user').last()).toContainText('Hang time (s): 60');
  });

  test('cancel and Escape leave composer mode without sending', async ({ page }) => {
    await openProgram(page);
    const before = await page.locator('.message.user').count();
    await page.locator('.quick-action-chip').nth(1).click();
    await page.locator('.qa-mode-cancel').click();
    await expect(page.locator('#quick-action-mode')).toBeHidden();
    await page.locator('.quick-action-chip').nth(1).click();
    await page.locator('#quick-action-mode .qa-mode-field-input').nth(0).press('Escape');
    await expect(page.locator('#quick-action-mode')).toBeHidden();
    await expect(page.locator('.message.user')).toHaveCount(before);
    await expect(page.locator('#send-btn')).toBeDisabled();
  });

  test('typing / lists the actions; arrows + Enter pick one', async ({ page }) => {
    await openProgram(page);
    await page.fill('#message-input', '/');
    const menu = page.locator('#quick-action-slash');
    await expect(menu).toBeVisible();
    await expect(menu.locator('.qa-slash-item')).toHaveCount(2);
    await page.fill('#message-input', '/log');
    await expect(menu.locator('.qa-slash-item')).toHaveCount(1);
    await page.keyboard.press('Enter');
    await expect(page.locator('#quick-action-mode .qa-mode-label')).toHaveText('Log & review');
    await expect(page.locator('#message-input')).toHaveValue('');
    await expect(menu).toBeHidden();
  });

  test('slash menu Enter never sends a bare slash message', async ({ page }) => {
    await openProgram(page);
    const before = await page.locator('.message.user').count();
    await page.fill('#message-input', '/');
    // ArrowDown then ArrowUp wraps back to the first item ("Plan today")
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowUp');
    await page.keyboard.press('Enter');
    await expect(page.locator('#quick-action-mode .qa-mode-label')).toHaveText('Plan today');
    await expect(page.locator('#message-input')).toHaveValue('');
    await expect(page.locator('.message.user')).toHaveCount(before);
  });

  test('editor adds an action that appears as a chip and persists (autosave)', async ({ page }) => {
    await openProgram(page);
    await page.locator('.program-quick-actions-btn').click();
    await page.locator('.qa-editor-add').click();
    await page.fill('.qa-detail-label', 'Week overview');
    await page.fill('.qa-detail-body', 'Summarize the week.');
    await page.locator('.qa-detail-done').click();
    await expect(page.locator('.quick-action-chip')).toHaveCount(3);
    await page.locator('.qa-editor-close').click();
    await expect(page.locator('.quick-action-chip')).toHaveCount(3);
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

  test('chip row is absent in a normal conversation', async ({ page }) => {
    await openProgram(page);
    await page.locator('.chat-header-back').click();
    await page.click('#new-chat-btn');
    await expect(page.locator('#quick-actions-bar')).toBeHidden();
    await page.fill('#message-input', '/');
    await expect(page.locator('#quick-action-slash')).toBeHidden();
  });
});

test.describe('Quick actions - mobile', () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test('chip row hides while typing and returns when the composer is cleared', async ({ page }) => {
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

  test('closing the editor over an unfinished action still saves it', async ({ page }) => {
    await openProgram(page);
    await page.locator('.quick-action-edit-chip').click();
    await page.locator('.qa-editor-add').click();
    await page.fill('.qa-detail-label', 'Evaluate');
    await page.fill('.qa-detail-body', 'Evaluate my session.');
    await page.locator('.qa-editor-close').click();
    await expect(page.locator('.quick-action-chip')).toHaveCount(3);
    await page.reload();
    await page.waitForSelector('#quick-actions-bar .quick-action-edit-chip');
    await expect(page.locator('.quick-action-chip').nth(2)).toContainText('Evaluate');
  });

  test('composer mode stacks the questions and sends with the note', async ({ page }) => {
    await openProgram(page);
    await page.locator('.quick-action-chip').nth(1).click();
    const mode = page.locator('#quick-action-mode');
    await expect(mode).toBeVisible();
    await mode.locator('.qa-mode-field-input').nth(0).fill('60');
    // Enter in the last field focuses the note on mobile instead of sending
    await mode.locator('.qa-mode-field-input').nth(1).press('Enter');
    await expect(page.locator('#message-input')).toBeFocused();
    await page.fill('#message-input', 'ok');
    await page.click('#send-btn');
    const last = page.locator('.message.user').last();
    await expect(last).toContainText('Hang time (s): 60');
    await expect(last).toContainText('ok');
    await expect(mode).toBeHidden();
  });
});
