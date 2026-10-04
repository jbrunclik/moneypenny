/**
 * Visual regression tests for deep research: the offer editor, the progress
 * panel mid-run and the report's chip.
 */
import { test, expect } from '../global-setup';
import type { APIRequestContext, Page } from '@playwright/test';

const OFFER = {
  question: 'Transfer a car registration',
  context: 'family of four, Prague',
  sub_questions: ['What do agencies charge?', 'How long does it take?', 'Which documents are needed?'],
};

/** Send a message whose reply carries the canned offer. */
async function sendOffer(page: Page, request: APIRequestContext, stepMs = 50, offer = OFFER): Promise<void> {
  // After the page fixture's reset, which clears the test's mock config
  await request.post('/test/set-deep-research', { data: { offer, step_ms: stepMs } });
  await page.goto('/');
  await page.waitForSelector('#new-chat-btn');
  await page.evaluate(() => {
    const banner = document.querySelector('.version-banner');
    if (banner) (banner as HTMLElement).style.display = 'none';
  });
  // On mobile, New chat lives in the sidebar
  if (await page.locator('#menu-btn').isVisible()) await page.click('#menu-btn');
  await page.click('#new-chat-btn');
  await page.fill('#message-input', 'Help me transfer a car registration');
  await page.click('#send-btn');
  await expect(page.locator('.research-offer__start')).toBeVisible({ timeout: 15000 });
}

test.describe('Visual: Deep research', () => {
  test('offer card', async ({ page, request }) => {
    await sendOffer(page, request);
    await expect(page.locator('.research-offer')).toHaveScreenshot('deep-research-offer.png');
  });

  test('offer card on mobile', async ({ page, request }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await sendOffer(page, request);
    await expect(page.locator('.research-offer')).toHaveScreenshot('deep-research-offer-mobile.png');
  });

  test('long context keeps its edit button inline on mobile', async ({ page, request }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const context =
      'Rides an endurance road bike April to October (about 5-32 °C, changeable spring and autumn weather); wants durable kit with no needless overlap.';
    await sendOffer(page, request, 50, { ...OFFER, context });
    await expect(page.locator('.research-offer__context')).toHaveScreenshot('deep-research-offer-long-context-mobile.png');
  });

  test('progress panel mid-run', async ({ page, request }) => {
    // Slow steps: the first item stays running while the screenshot is taken
    await sendOffer(page, request, 10_000);
    await page.locator('.research-offer__start').click();
    const panel = page.locator('.research-progress');
    await expect(panel.locator('.research-progress__item--started')).toHaveCount(1, { timeout: 15000 });
    // Items and footer only: a finding can land in the feed at any moment
    // The spinner's antialiasing varies frame to frame in WebKit
    await expect(panel.locator('.research-progress__items')).toHaveScreenshot('deep-research-progress-items.png', {
      mask: [panel.locator('.research-progress__spinner')],
    });
    await expect(panel.locator('.research-progress__footer')).toHaveScreenshot('deep-research-progress-footer.png', {
      mask: [panel.locator('.research-progress__elapsed')],
    });
  });

  test('action row of a started run', async ({ page, request }) => {
    await sendOffer(page, request);
    await page.locator('.research-offer__start').click();
    const row = page.locator('.message--action');
    await expect(row.locator('.action-row__source')).toBeVisible({ timeout: 15000 });
    await expect(row.locator('.action-row')).toHaveScreenshot('deep-research-action-row.png');
  });

  test('action row on mobile', async ({ page, request }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await sendOffer(page, request);
    await page.locator('.research-offer__start').click();
    const row = page.locator('.message--action');
    await expect(row.locator('.action-row__source')).toBeVisible({ timeout: 15000 });
    await expect(row).toHaveScreenshot('deep-research-action-row-mobile.png');
  });

  test('report chip, expanded', async ({ page, request }) => {
    await sendOffer(page, request);
    await page.locator('.research-offer__start').click();
    const chip = page.locator('.research-chip');
    await expect(chip).toBeVisible({ timeout: 15000 });
    await chip.locator('summary').click();
    // The duration varies run to run
    await chip.locator('summary').evaluate((el) => {
      el.textContent = (el.textContent ?? '').replace(/\d+ min/, '1 min');
    });
    await expect(chip).toHaveScreenshot('deep-research-chip.png');
  });
});
