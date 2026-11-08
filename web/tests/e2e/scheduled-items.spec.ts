/**
 * E2E tests for items scheduled from chat: the chat header chip and its sheet
 * (cancel), the label on a turn an item delivered, and the Command Center's
 * "From chats" lane.
 */
import type { Page } from '@playwright/test';
import { test, expect } from '../global-setup';

interface SeedItem {
  kind: 'reminder' | 'check_in' | 'watcher' | 'recurring';
  text: string;
  end_condition?: string;
  interval_hours?: number;
}

async function seedChat(page: Page, items: SeedItem[], title = "Dog's tail"): Promise<string> {
  const response = await page.request.post('/test/seed', {
    data: {
      conversations: [
        {
          title,
          messages: [
            { role: 'user', content: 'Check with me on Friday how it is healing' },
            { role: 'assistant', content: "Sure, I'll ask you on Friday at 18:00." },
            {
              role: 'assistant',
              content: "How's the tail looking - is the fur growing back?",
              delivery: { kind: 'check_in', label: 'Check-in · Fri 18:00' },
            },
          ],
          scheduled_items: items,
        },
      ],
    },
  });
  expect(response.ok()).toBeTruthy();
  const body = (await response.json()) as { conversation_ids: string[] };
  const id = body.conversation_ids[0];
  if (id === undefined) throw new Error('seed returned no conversation id');
  return id;
}

const WATCHER: SeedItem = {
  kind: 'watcher',
  text: "the school's job board",
  end_condition: 'a teacher job is posted',
  interval_hours: 24,
};
const REMINDER: SeedItem = { kind: 'reminder', text: 'Order dog food' };

test.describe('Scheduled items', () => {
  test('the chip lists the chat items and cancel removes one (desktop)', async ({ page }) => {
    const convId = await seedChat(page, [WATCHER, REMINDER]);
    await page.goto(`/#/conversations/${convId}`);

    const chip = page.locator('#conversation-schedules');
    await expect(chip).toBeVisible();
    await expect(chip).toContainText('2');
    await chip.click();

    const sheet = page.locator('#schedules-popup');
    await expect(sheet).toBeVisible();
    await expect(sheet).toContainText("the school's job board");
    await expect(sheet).toContainText('until a teacher job is posted');
    await expect(sheet.locator('.schedule-item-pause')).toHaveCount(1); // the watcher only

    await sheet.locator('.schedule-item', { hasText: 'Order dog food' }).locator('.schedule-item-cancel').click();
    await expect(sheet.locator('.schedule-item')).toHaveCount(1);
    await expect(chip).toContainText('1');
  });

  test('shows on the mobile header too', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    const convId = await seedChat(page, [WATCHER]);
    await page.goto(`/#/conversations/${convId}`);

    const chip = page.locator('#conversation-schedules-mobile');
    await expect(chip).toBeVisible();
    await chip.click();
    await expect(page.locator('#schedules-popup')).toContainText("the school's job board");
  });

  test('a delivered turn carries its label; no chip without items', async ({ page }) => {
    const convId = await seedChat(page, []);
    await page.goto(`/#/conversations/${convId}`);

    const delivered = page.locator('.message.assistant', { hasText: "How's the tail looking" });
    await expect(delivered.locator('.message-delivery')).toHaveText('Check-in · Fri 18:00');
    await expect(page.locator('#conversation-schedules')).toBeHidden();
  });

  test('the Command Center shows them above the agents, linking to the chat', async ({ page }) => {
    const convId = await seedChat(page, [WATCHER]);
    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');

    const lane = page.locator('.command-center-section--chat-items');
    await expect(lane).toContainText('From chats');
    await expect(lane).toContainText("the school's job board");
    await lane.locator('.chat-item-chat').click();
    await expect(page).toHaveURL(new RegExp(`#/conversations/${convId}$`));
    await expect(page.locator('#conversation-schedules')).toBeVisible();
  });

  test("a trashed chat's items are not in the lane", async ({ page }) => {
    const convId = await seedChat(page, [WATCHER]);
    const trashed = await page.request.delete(`/api/conversations/${convId}`);
    expect(trashed.ok()).toBeTruthy();

    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');
    await expect(page.locator('.command-center-section--chat-items')).toHaveCount(0);
  });
});

test.describe('Scheduled items in a standing chat', () => {
  async function agentChat(page: Page): Promise<string> {
    const created = await page.request.post('/api/agents', {
      data: { name: 'Garden helper', system_prompt: 'Help with the garden', schedule: null },
    });
    expect(created.ok()).toBeTruthy();
    const agent = (await created.json()) as { conversation_id: string };
    const seeded = await page.request.post('/test/seed-item', {
      data: { conversation_id: agent.conversation_id, item: { kind: 'reminder', text: 'Water the tomatoes' } },
    });
    expect(seeded.ok()).toBeTruthy();
    return agent.conversation_id;
  }

  test('the chip shows in an agent chat (desktop)', async ({ page }) => {
    const convId = await agentChat(page);
    await page.goto(`/#/conversations/${convId}`);

    const chip = page.locator('#conversation-schedules');
    await expect(chip).toBeVisible();
    await chip.click();
    await expect(page.locator('#schedules-popup')).toContainText('Water the tomatoes');
  });

  test('the chip shows in an agent chat (mobile)', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    const convId = await agentChat(page);
    await page.goto(`/#/conversations/${convId}`);

    await expect(page.locator('#conversation-schedules-mobile')).toBeVisible();
  });
});
