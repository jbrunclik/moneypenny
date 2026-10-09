/**
 * Visual regression tests for the DARK theme - the default (`:root`), which
 * every other visual test skips because Playwright renders the light scheme.
 * A focused set of core screens: the chat, a dialog, the turn summary, the
 * planner and mobile.
 */
import type { Page } from '@playwright/test';
import { test, expect } from '../global-setup';

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
});

async function newChat(page: Page): Promise<void> {
  await page.goto('/');
  await page.waitForSelector('#new-chat-btn', { state: 'attached' });
  if (await page.locator('#menu-btn').isVisible()) await page.click('#menu-btn');
  await page.click('#new-chat-btn');
}

async function sendAndWait(page: Page, text: string): Promise<void> {
  await page.fill('#message-input', text);
  await page.click('#send-btn');
  await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 15000 });
  // Pin the visible message clock (baselines must not depend on the minute)
  await page.evaluate(() => {
    for (const el of document.querySelectorAll('.message-time')) el.textContent = '12:00 PM';
  });
  await page.mouse.move(0, 0);
  await page.waitForTimeout(400);
}

test.describe('Visual: Dark theme', () => {
  test('empty conversation', async ({ page }) => {
    await newChat(page);
    await page.waitForSelector('.welcome-message');
    await page.waitForTimeout(500);
    await expect(page).toHaveScreenshot('dark-empty-conversation.png');
  });

  test('conversation with a turn summary', async ({ page }) => {
    await newChat(page);
    // "think" makes the mock emit a thinking event -> collapsed "Thought" summary
    await sendAndWait(page, 'Please think about the best route to Brno');
    await expect(page).toHaveScreenshot('dark-conversation.png');
  });

  test('confirm dialog over a conversation', async ({ page }) => {
    await newChat(page);
    await sendAndWait(page, 'Something to delete');
    const item = page.locator('.conversation-item').first();
    await item.hover();
    await item.locator('.conversation-delete').click({ force: true });
    await page.waitForSelector('.modal-container:not(.modal-hidden)');
    await page.locator('#message-input').blur();
    await page.waitForTimeout(300);
    await expect(page).toHaveScreenshot('dark-confirm-dialog.png');
  });

  test('planner dashboard', async ({ page }) => {
    await page.request.post('/test/set-planner-dashboard', {
      data: {
        dashboard: {
          days: [
            {
              date: '2024-12-25',
              day_name: 'Today',
              events: [
                {
                  id: 'e1',
                  summary: 'Team Standup',
                  start: '2024-12-25T09:00:00',
                  end: '2024-12-25T09:30:00',
                  is_all_day: false,
                  location: 'Conference Room A',
                },
              ],
              tasks: [{ id: 't1', content: 'Review pull requests', priority: 3, due: null, project: 'Development' }],
            },
            { date: '2024-12-26', day_name: 'Tomorrow', events: [], tasks: [] },
          ],
          overdue_tasks: [],
          todoist_connected: true,
          calendar_connected: true,
          garmin_connected: false,
          weather_connected: false,
          server_time: '2024-12-25T08:00:00',
        },
      },
    });
    await page.goto('/#/planner');
    await page.waitForSelector('#planner-dashboard');
    await page.waitForTimeout(300);
    await expect(page.locator('#planner-dashboard')).toHaveScreenshot('dark-planner.png', {
      mask: [page.locator('.dashboard-date')],
    });
  });

  test.describe('mobile', () => {
    test.use({ viewport: { width: 375, height: 812 } });

    test('conversation', async ({ page }) => {
      await newChat(page);
      await sendAndWait(page, 'Hello from a phone');
      await expect(page).toHaveScreenshot('dark-mobile-conversation.png');
    });
  });
});
