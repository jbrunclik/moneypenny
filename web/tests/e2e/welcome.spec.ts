/**
 * E2E tests for the empty-conversation welcome: greeting and (desktop) the
 * composer centred under it.
 */
import { test, expect } from '../global-setup';

test('desktop composer sits under the greeting, then returns to the bottom on send', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/');
  await page.waitForSelector('#new-chat-btn');
  await page.click('#new-chat-btn');
  await expect(page.locator('.welcome-message h2')).toHaveText(/^What’s on your mind/);

  const pill = page.locator('.input-container');
  const centred = (await pill.boundingBox())!;
  expect(centred.y).toBeLessThan(900 * 0.7);

  await page.fill('#message-input', 'Hello there');
  await page.click('#send-btn');
  await expect(page.locator('.message.user')).toBeInViewport();
  // Slid back to the bottom once the welcome is gone
  await expect
    .poll(async () => {
      const box = (await pill.boundingBox())!;
      return box.y + box.height;
    })
    .toBeGreaterThan(900 - 60);
  await expect(page.locator('.message.assistant:not(.streaming)')).toBeInViewport({ timeout: 15000 });
});

test('mobile keeps the composer at the bottom on an empty conversation', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto('/');
  await page.waitForSelector('#menu-btn');
  const box = (await page.locator('.input-container').boundingBox())!;
  expect(box.y + box.height).toBeGreaterThan(812 - 60);
});
