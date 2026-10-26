/**
 * Visual regression for artifacts: the design-system kitchen sink in a
 * sandboxed frame, light and dark, desktop and mobile.
 */
import { readFileSync } from 'fs';
import type { APIRequestContext, Page } from '@playwright/test';
import { test, expect } from '../global-setup';
import { pageSettled } from '../e2e/waits';

const KITCHEN_SINK = readFileSync('tests/fixtures/artifact-kitchen-sink.html', 'utf8');

async function showKitchenSink(page: Page, request: APIRequestContext): Promise<void> {
  // After the page fixture's reset, which clears the test's mock config
  await request.post('/test/set-artifact', { data: { title: 'Svíčková', html: KITCHEN_SINK } });
  await page.goto('/');
  await page.waitForSelector('#new-chat-btn', { state: 'attached' });
  await page.evaluate(() => {
    const banner = document.querySelector('.version-banner');
    if (banner) (banner as HTMLElement).style.display = 'none';
  });
  if (await page.locator('#menu-btn').isVisible()) await page.click('#menu-btn');
  await page.click('#new-chat-btn');
  await page.fill('#message-input', 'Svíčková recipe please');
  await page.click('#send-btn');
  await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 15000 });
  const frame = page.locator('.artifact-frame').first().contentFrame();
  // Probes settled, fonts in, height reported
  await expect(frame.locator('#net')).toHaveText('blocked', { timeout: 15000 });
  await frame.locator('html').evaluate(() => document.fonts.ready);
  await expect
    .poll(async () => (await page.locator('.artifact-frame').first().boundingBox())?.height ?? 0)
    .toBeGreaterThan(400);
  // The floating composer would cover the card's lower part
  await page.addStyleTag({ content: '.input-area { visibility: hidden; }' });
  await page.mouse.move(0, 0);
  await pageSettled(page);
}

for (const scheme of ['light', 'dark'] as const) {
  test.describe(`Visual: Artifacts (${scheme})`, () => {
    test.beforeEach(async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
    });

    test('kitchen sink', async ({ page, request }) => {
      // Tall enough that the frame is not capped at ARTIFACT_MAX_HEIGHT_VH
      await page.setViewportSize({ width: 1280, height: 1600 });
      await showKitchenSink(page, request);
      await expect(page.locator('.artifact-card').first()).toHaveScreenshot(`artifact-kitchen-sink-${scheme}.png`);
    });

    test('kitchen sink on mobile', async ({ page, request }) => {
      await page.setViewportSize({ width: 390, height: 2200 });
      await showKitchenSink(page, request);
      await expect(page.locator('.artifact-card').first()).toHaveScreenshot(
        `artifact-kitchen-sink-${scheme}-mobile.png`
      );
    });
  });
}
