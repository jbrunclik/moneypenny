/**
 * Changes made on ANOTHER device reach this one on the regular poll tick.
 *
 * The other device is the API (same user). Every test uses the incremental
 * sync only: the old timestamp sync noticed archive/trash/delete solely on a
 * full sync, which a tab that stays visible never runs - so chats deleted on
 * the phone lingered on the desktop. (The older sync.spec.ts tests forced
 * full syncs and masked that.)
 */
import { test, expect } from '../global-setup';

declare global {
  interface Window {
    __testIncrementalSync: () => Promise<void>;
  }
}

let ids: { alpha: string; beta: string };

test.beforeEach(async ({ page, request }) => {
  const seeded = await request.post('/test/seed', {
    data: {
      conversations: [
        { title: 'Alpha', messages: [{ role: 'user', content: 'a?' }, { role: 'assistant', content: 'a!' }] },
        { title: 'Beta', messages: [{ role: 'user', content: 'b?' }, { role: 'assistant', content: 'b!' }] },
      ],
    },
  });
  const [alpha, beta] = (await seeded.json()).conversation_ids as string[];
  ids = { alpha, beta };
  await page.goto('/');
  await expect(page.locator('.conversation-item-wrapper', { hasText: 'Alpha' })).toBeVisible();
});

const item = (page: import('@playwright/test').Page, title: string) =>
  page.locator('.conversation-item-wrapper', { hasText: title });

async function poll(page: import('@playwright/test').Page): Promise<void> {
  await page.evaluate(() => window.__testIncrementalSync());
}

test('a chat archived on another device leaves the sidebar', async ({ page, request }) => {
  await request.post(`/api/conversations/${ids.alpha}/archive`);
  await poll(page);
  await expect(item(page, 'Alpha')).toHaveCount(0);
  await expect(item(page, 'Beta')).toBeVisible();
});

test('a chat moved to the trash on another device leaves the sidebar', async ({ page, request }) => {
  await request.delete(`/api/conversations/${ids.alpha}`);
  await poll(page);
  await expect(item(page, 'Alpha')).toHaveCount(0);
});

test('a chat deleted for good on another device leaves the sidebar', async ({ page, request }) => {
  await request.delete(`/api/conversations/${ids.alpha}`);
  await request.delete(`/api/conversations/${ids.alpha}/permanent`);
  await poll(page);
  await expect(item(page, 'Alpha')).toHaveCount(0);
});

test('the open chat trashed on another device closes with a notice', async ({ page, request }) => {
  await item(page, 'Alpha').click();
  await expect(page.locator('.message.assistant')).toContainText('a!');

  await request.delete(`/api/conversations/${ids.alpha}`);
  await poll(page);

  await expect(page.locator('.toast')).toContainText('moved to the trash on another device');
  await expect(page.locator('.message.assistant')).toHaveCount(0);
});

test('a chat restored on another device comes back without an unread badge', async ({ page, request }) => {
  await request.delete(`/api/conversations/${ids.alpha}`);
  await poll(page);
  await expect(item(page, 'Alpha')).toHaveCount(0);

  await request.post(`/api/conversations/${ids.alpha}/restore`);
  await poll(page);

  await expect(item(page, 'Alpha')).toBeVisible();
  await expect(item(page, 'Alpha').locator('.unread-badge')).toHaveCount(0);
});

test('a pin on another device moves the chat to Pinned', async ({ page, request }) => {
  await request.post(`/api/conversations/${ids.beta}/pin`);
  await poll(page);
  await expect(page.locator('.conversation-group-label').first()).toHaveText('Pinned');
  await expect(page.locator('.conversation-item-wrapper').first()).toContainText('Beta');
});

test('a rename on another device shows up', async ({ page, request }) => {
  await request.patch(`/api/conversations/${ids.beta}`, { data: { title: 'Beta renamed' } });
  await poll(page);
  await expect(item(page, 'Beta renamed')).toBeVisible();
});

test.describe('the open chat', () => {
  test.beforeEach(async ({ page }) => {
    // Batch mode on the API side; the open page only reads
    await item(page, 'Alpha').click();
    await expect(page.locator('.message.assistant')).toContainText('a!');
    // Marks the rendered DOM: a full re-render would drop it
    await page.evaluate(() => document.querySelector('.message.user')!.setAttribute('data-kept', '1'));
  });

  test('messages sent on another device appear in place, without a banner or reload', async ({ page, request }) => {
    await request.post(`/api/conversations/${ids.alpha}/chat/batch`, { data: { message: 'From the phone' } });
    await poll(page);

    await expect(page.locator('.message.user').last()).toContainText('From the phone');
    await expect(page.locator('.message.assistant').last()).toContainText('mock response');
    await expect(page.locator('.new-messages-banner')).toHaveCount(0);
    await expect(page.locator('.message.user[data-kept="1"]')).toHaveCount(1);
  });

  test('a message deleted on another device disappears', async ({ page, request }) => {
    const reply = await page.locator('.message.assistant').last().getAttribute('data-message-id');
    await request.delete(`/api/messages/${reply}`);
    await poll(page);

    await expect(page.locator(`.message[data-message-id="${reply}"]`)).toHaveCount(0);
  });

  test('a reply streaming on another device streams in here too', async ({ page, context, request }) => {
    await request.post('/test/set-stream-delay', { data: { delay_ms: 150 } });
    const phone = await context.newPage();
    await phone.goto(`/#/conversations/${ids.alpha}`);
    await expect(phone.locator('.message.assistant')).toContainText('a!');
    await phone.fill('#message-input', 'Stream from the phone');
    await phone.click('#send-btn');
    await expect(phone.locator('.message.assistant.streaming')).toBeVisible();

    // Successive poll ticks: the reply's placeholder is saved a moment
    // after the user message
    const streaming = page.locator('.message.assistant.streaming');
    await expect
      .poll(async () => {
        await poll(page);
        return streaming.count();
      }, { timeout: 10000 })
      .toBe(1);

    const live = page.locator('.message.assistant').last();
    await expect(page.locator('.message.user').last()).toContainText('Stream from the phone');
    await expect(live).toContainText('mock response', { timeout: 20000 });
    await expect(live).not.toHaveClass(/streaming/, { timeout: 20000 });
    await request.post('/test/set-stream-delay', { data: { delay_ms: 10 } });
    await phone.close();
  });
});

test('a rename on another device updates the open chat\'s header too', async ({ page, request }) => {
  await item(page, 'Alpha').click();
  await expect(page.locator('.message.assistant')).toContainText('a!');

  await request.patch(`/api/conversations/${ids.alpha}`, { data: { title: 'Alpha renamed' } });
  await poll(page);

  await expect(page.locator('#current-chat-title').first()).toHaveText('Alpha renamed');
});

test('the planner merges messages from another device in place', async ({ page, request }) => {
  await request.post('/test/set-planner-integrations', { data: { todoist: true, calendar: false } });
  await page.goto('/#/planner');
  await expect(page.locator('#planner-dashboard')).toBeVisible({ timeout: 10000 });
  const planner = await (await request.get('/api/planner/conversation')).json();
  const plannerId = (planner.id ?? planner.conversation?.id) as string;
  await page.evaluate(() => document.getElementById('planner-dashboard')!.setAttribute('data-kept', '1'));

  await request.post(`/api/conversations/${plannerId}/chat/batch`, { data: { message: 'Plan from the phone' } });
  // The planner has its own count-based poll inside the same tick
  await poll(page);

  await expect(page.locator('.message.user').last()).toContainText('Plan from the phone');
  await expect(page.locator('.new-messages-banner')).toHaveCount(0);
  await expect(page.locator('#planner-dashboard[data-kept="1"]')).toHaveCount(1);
});
