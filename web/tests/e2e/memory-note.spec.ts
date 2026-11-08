/**
 * E2E: the "Memory updated" note the background memory review leaves under a
 * reply, and that it opens Memories (the Data page).
 */
import type { Page } from '@playwright/test';
import { test, expect } from '../global-setup';

async function seedChat(page: Page): Promise<string> {
  const response = await page.request.post('/test/seed', {
    data: {
      conversations: [
        {
          title: 'Dinner plans',
          messages: [
            { role: 'user', content: 'Dinner ideas for Tuesday? Ema has ballet until 17:00.' },
            { role: 'assistant', content: 'How about a quick risotto?', memory_note: 'Ema - ballet on Tuesdays' },
          ],
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

for (const [name, viewport] of [
  ['desktop', { width: 1280, height: 800 }],
  ['mobile', { width: 375, height: 812 }],
] as const) {
  test(`a reply shows what memory review saved and opens Memories (${name})`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const convId = await seedChat(page);
    await page.goto(`/#/conversations/${convId}`);

    const reply = page.locator('.message.assistant', { hasText: 'quick risotto' });
    const note = reply.locator('.message-memory-note');
    await expect(note).toHaveText('Memory updated: Ema - ballet on Tuesdays');

    await note.click();
    await expect(page.locator('.kv-store')).toBeVisible();
  });
}

test('a reply without a memory note shows none', async ({ page }) => {
  const response = await page.request.post('/test/seed', {
    data: { conversations: [{ title: 'Plain', messages: [{ role: 'assistant', content: 'Hello' }] }] },
  });
  const { conversation_ids } = (await response.json()) as { conversation_ids: string[] };
  await page.goto(`/#/conversations/${conversation_ids[0]}`);
  await expect(page.locator('.message.assistant', { hasText: 'Hello' })).toBeVisible();
  await expect(page.locator('.message-memory-note')).toHaveCount(0);
});
