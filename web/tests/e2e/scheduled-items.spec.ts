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
  schedule?: string;
  status?: 'active' | 'paused';
  grants?: string[];
  paused_reason?: string;
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

const PAUSED_JOB: SeedItem = {
  kind: 'recurring',
  text: "Plan tomorrow's ride",
  schedule: '0 * * * *',
  status: 'paused',
  grants: ['garmin_connect'],
  paused_reason: 'failures',
};

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

  test('the Command Center lists them as jobs; a row opens its chat', async ({ page }) => {
    const convId = await seedChat(page, [WATCHER]);
    await page.goto('/#/agents');

    const row = page.locator('.job-row', { hasText: "the school's job board" });
    await expect(row.locator('.job-meta')).toContainText("Dog's tail");
    await row.locator('.job-title').click();
    await expect(page).toHaveURL(new RegExp(`#/conversations/${convId}$`));
    await expect(page.locator('#conversation-schedules')).toBeVisible();
  });

  test("a trashed chat's items are not in the job list", async ({ page }) => {
    const convId = await seedChat(page, [WATCHER]);
    const trashed = await page.request.delete(`/api/conversations/${convId}`);
    expect(trashed.ok()).toBeTruthy();

    await page.goto('/#/agents');
    await expect(page.locator('.jobs-empty')).toBeVisible();
    await expect(page.locator('.job-row')).toHaveCount(0);
  });
});

test.describe('Scheduled items in a standing chat', () => {
  async function agentChat(page: Page): Promise<string> {
    const created = await page.request.post('/api/jobs', {
      data: { name: 'Garden helper', instructions: 'Help with the garden', schedule: null },
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

  for (const [label, viewport, chipId] of [
    ['desktop', { width: 1280, height: 800 }, '#conversation-schedules'],
    ['mobile', { width: 375, height: 812 }, '#conversation-schedules-mobile'],
  ] as const) {
    test(`a paused standing job offers Resume and says why it paused (${label})`, async ({ page }) => {
      await page.setViewportSize(viewport);
      const convId = await seedChat(page, [PAUSED_JOB], 'Coach');
      await page.goto(`/#/conversations/${convId}`);

      await page.locator(chipId).click();
      const row = page.locator('#schedules-popup .schedule-item', { hasText: "Plan tomorrow's ride" });
      await expect(row.locator('.schedule-item-meta')).toContainText('paused after failing');
      // One play button: a paused job resumes (Run now comes back once it runs again)
      await expect(row.locator('.schedule-item-pause')).toHaveAttribute('aria-label', 'Resume');
      await expect(row.locator('.schedule-item-run')).toHaveCount(0);
    });
  }
});

test.describe('A chat with jobs, at a glance and as an agent', () => {
  for (const [label, viewport] of [
    ['desktop', { width: 1280, height: 800 }],
    ['mobile', { width: 375, height: 812 }],
  ] as const) {
    test(`the sidebar row shows a clock with the count (${label})`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await seedChat(page, [WATCHER, REMINDER]);
      await page.goto('/');
      if (label === 'mobile') await page.click('#menu-btn');

      const clock = page.locator('.conversation-item-wrapper', { hasText: "Dog's tail" }).locator('.conversation-jobs');
      await expect(clock).toBeVisible();
      await expect(clock).toHaveText('2');
      await expect(clock).toHaveAttribute('title', '2 scheduled jobs');
    });
  }

  test('a watcher becomes an agent from the job list', async ({ page }) => {
    await seedChat(page, [WATCHER]);
    await page.goto('/#/agents');

    const row = page.locator('.job-row', { hasText: "the school's job board" });
    await row.locator('.job-make-agent').click();
    await expect(page.locator('#agent-editor-title')).toHaveText('Make it an agent');
    await expect(page.locator('#agent-name')).toHaveValue("the school's job board");
    await expect(page.locator('#agent-system-prompt')).toHaveValue(/Stop when: a teacher job is posted/);
    await page.click('.agent-editor-save');

    // The agent took over: its own row, and the chat's watcher is gone
    await expect(page.locator('.job-row .job-make-agent')).toHaveCount(0);
    await expect(page.locator('.job-row', { hasText: "the school's job board" }).locator('.job-edit')).toBeVisible();
  });
});
