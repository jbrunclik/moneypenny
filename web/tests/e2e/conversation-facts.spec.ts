/**
 * E2E tests for the conversation facts chip: a conversation with settled
 * facts shows a header chip with the count, and the chip opens a read-only
 * popup listing them.
 */
import type { Page } from '@playwright/test';
import { test, expect } from '../global-setup';

async function seedConversation(page: Page, facts: { key: string; text: string }[]): Promise<string> {
  const response = await page.request.post('/test/seed', {
    data: {
      conversations: [
        {
          title: 'Bedroom renovation',
          messages: [
            { role: 'user', content: 'All partitions are reinforced concrete' },
            { role: 'assistant', content: 'Noted.' },
          ],
          facts,
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

const FACTS = [
  { key: 'walls', text: 'All partitions are reinforced concrete except one brick wall' },
  { key: 'blinds', text: 'Blackout blinds already installed' },
];

test.describe('Conversation facts chip', () => {
  test('shows the count and opens a read-only list (desktop)', async ({ page }) => {
    const convId = await seedConversation(page, FACTS);
    await page.goto(`/#/conversations/${convId}`);

    const chip = page.locator('#conversation-facts');
    await expect(chip).toBeVisible();
    await expect(chip).toContainText('2');
    await chip.click();

    const popup = page.locator('#facts-popup');
    await expect(popup).toBeVisible();
    await expect(popup).toContainText('Blackout blinds already installed');
    await expect(popup).toContainText('To change a fact, tell Moneypenny in the chat.');
    await expect(popup.locator('input, textarea')).toHaveCount(0);
  });

  test('shows on the mobile header too', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    const convId = await seedConversation(page, FACTS);
    await page.goto(`/#/conversations/${convId}`);

    const chip = page.locator('#conversation-facts-mobile');
    await expect(chip).toBeVisible();
    await chip.click();
    await expect(page.locator('#facts-popup')).toContainText('walls');
  });

  test('stays hidden without facts', async ({ page }) => {
    const convId = await seedConversation(page, []);
    await page.goto(`/#/conversations/${convId}`);
    await expect(page.locator('.message.assistant')).toContainText('Noted.');
    await expect(page.locator('#conversation-facts')).toBeHidden();
  });
});
