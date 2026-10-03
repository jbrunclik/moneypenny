/**
 * Visual regression tests for grounding annotations: underlined claims and
 * source numbers, the claim card, and the claims list on mobile.
 */
import { test, expect } from '../global-setup';
import type { APIRequestContext, Page } from '@playwright/test';

const ANNOTATIONS = {
  summary: { checked: true, source_count: 1 },
  annotations: [
    { type: 'claim', verdict: 'supported', quote: 'This is a', source: 1, source_quote: 'This is' },
    { type: 'claim', verdict: 'not_found', quote: 'mock response', prefix: 'This is a ', reason: 'Not in the pages I read.' },
    { type: 'claim', verdict: 'contradicted', quote: 'Draw my claims', reason: 'The source says otherwise.' },
  ],
};

/** Send a message whose reply gets the canned annotations. */
async function sendAnnotated(page: Page, request: APIRequestContext): Promise<void> {
  // After the page fixture's reset, which clears the test's mock config
  await request.post('/test/set-grounding-result', { data: ANNOTATIONS });
  await page.goto('/');
  await page.waitForSelector('#new-chat-btn');
  await page.evaluate(() => {
    const banner = document.querySelector('.version-banner');
    if (banner) (banner as HTMLElement).style.display = 'none';
  });
  // On mobile, New chat lives in the sidebar
  if (await page.locator('#menu-btn').isVisible()) await page.click('#menu-btn');
  await page.click('#new-chat-btn');
  await page.fill('#message-input', 'Draw my claims');
  await page.click('#send-btn');
  await expect(page.locator('.grounding-footer[role="button"]')).toBeVisible({ timeout: 15000 });
}

test.describe('Visual: Grounding annotations', () => {
  test('underlines, source number and footer', async ({ page, request }) => {
    await sendAnnotated(page, request);
    const content = page.locator('.message.assistant .message-content-wrapper').last();
    await expect(content.locator('.message-content')).toHaveScreenshot('grounding-message.png');
    await expect(content.locator('.grounding-footer')).toHaveScreenshot('grounding-footer.png');
  });

  test('claim card', async ({ page, request }) => {
    await sendAnnotated(page, request);
    await page.locator('.message.assistant .claim--not_found').first().click();
    await expect(page.locator('#claim-card')).toHaveScreenshot('grounding-claim-card.png');
  });

  test('claims list on mobile', async ({ page, request }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await sendAnnotated(page, request);
    await page.locator('.grounding-footer').click();
    await expect(page.locator('.claims-sheet__panel')).toHaveScreenshot('grounding-claims-sheet-mobile.png');
  });
});
