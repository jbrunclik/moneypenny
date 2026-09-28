/**
 * E2E tests for the conversation compaction indicator: once older messages
 * are replaced by a running summary for the model, the UI shows a header
 * chip, a divider after the last summarized message, and a detail popup.
 */
import type { Page } from '@playwright/test';
import { test, expect } from '../global-setup';

const TOTAL_MESSAGES = 40; // above CONVERSATION_COMPACTION_THRESHOLD (30)
const SUMMARIZED = 20;

async function seedCompactedConversation(page: Page, generation: number): Promise<string> {
  const messages = Array.from({ length: TOTAL_MESSAGES }, (_, i) => ({
    role: i % 2 === 0 ? 'user' : 'assistant',
    content: `Message number ${i + 1}`,
  }));
  const response = await page.request.post('/test/seed', {
    data: {
      conversations: [
        {
          title: 'Long trip planning',
          messages,
          compaction: {
            summary: 'The user is planning a **trip to Lisbon** in May.',
            covered_count: SUMMARIZED,
            generation,
          },
        },
      ],
    },
  });
  expect(response.ok()).toBeTruthy();
  const body = (await response.json()) as { conversation_ids: string[] };
  return body.conversation_ids[0];
}

test.describe('Conversation compaction indicator', () => {
  test('shows the divider, dims summarized messages, and opens the popup', async ({ page }) => {
    const convId = await seedCompactedConversation(page, 4);
    await page.goto(`/#/conversations/${convId}`);

    const divider = page.locator('#messages .compaction-divider');
    await expect(divider).toBeVisible();
    await expect(divider).toContainText(`${SUMMARIZED} messages above summarized`);
    await expect(divider).toContainText('×4');

    // The divider follows the last summarized message
    const previous = divider.locator('xpath=preceding-sibling::div[contains(@class,"message")][1]');
    await expect(previous).toContainText(`Message number ${SUMMARIZED}`);
    await expect(page.locator('.message.message--compacted')).toHaveCount(SUMMARIZED);

    const chip = page.locator('#conversation-compaction');
    await expect(chip).toBeVisible();
    await expect(chip).toContainText(`${SUMMARIZED}/${TOTAL_MESSAGES}`);
    await expect(chip).toHaveClass(/compaction--deep/);

    await chip.click();
    const popup = page.locator('#compaction-popup');
    await expect(popup).toBeVisible();
    await expect(popup).toContainText(`${SUMMARIZED} of ${TOTAL_MESSAGES} messages`);
    await expect(popup.locator('.compaction-summary strong')).toHaveText('trip to Lisbon');
    await page.keyboard.press('Escape');
    await expect(popup).toBeHidden();

    // Loading the conversation still lands at the bottom
    const atBottom = await page.locator('#messages').evaluate(
      (el) => el.scrollHeight - el.scrollTop - el.clientHeight < 50
    );
    expect(atBottom).toBe(true);
  });

  test('stays hidden for a conversation without compaction', async ({ page }) => {
    const response = await page.request.post('/test/seed', {
      data: {
        conversations: [
          {
            title: 'Short chat',
            messages: [
              { role: 'user', content: 'Hi' },
              { role: 'assistant', content: 'Hello' },
            ],
          },
        ],
      },
    });
    const { conversation_ids } = (await response.json()) as { conversation_ids: string[] };
    await page.goto(`/#/conversations/${conversation_ids[0]}`);
    await expect(page.locator('.message.assistant')).toBeVisible();

    await expect(page.locator('#conversation-compaction')).toBeHidden();
    await expect(page.locator('.compaction-divider')).toHaveCount(0);
  });
});

test.describe('Conversation compaction indicator (mobile)', () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test('shows a compact chip in the mobile header', async ({ page }) => {
    const convId = await seedCompactedConversation(page, 1);
    await page.goto(`/#/conversations/${convId}`);

    const chip = page.locator('#conversation-compaction-mobile');
    await expect(chip).toBeVisible();
    await expect(chip).toContainText('×1');
    // Counts collapse on mobile to fit the header
    await expect(chip.locator('.compaction-chip-counts')).toBeHidden();

    await chip.click();
    await expect(page.locator('#compaction-popup')).toBeVisible();
  });
});
