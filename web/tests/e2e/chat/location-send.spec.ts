/**
 * With location sharing on, a slow GPS fix must not delay the thinking bar:
 * the send used to await the fix (up to LOCATION_FIX_TIMEOUT_MS) before the
 * streaming bubble existed, so the user saw only their own message.
 */
import { test, expect, setStreamDelay, resetStreamDelay } from './fixtures';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('location_sharing_enabled', 'true');
    navigator.geolocation.getCurrentPosition = (ok) => {
      setTimeout(
        () => ok({ coords: { latitude: 50.08, longitude: 14.42, accuracy: 10 }, timestamp: Date.now() } as GeolocationPosition),
        2000
      );
    };
  });
});

test.afterEach(async ({ page }) => {
  await resetStreamDelay(page);
});

test('the thinking bar appears at once while the location fix is still pending', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#new-chat-btn');
  await page.click('#new-chat-btn');
  await setStreamDelay(page, 50);

  await page.fill('#message-input', 'Where is the nearest bakery?');
  await page.click('#send-btn');
  // Well before the 2s fix resolves
  await expect(page.locator('.message.assistant.streaming .thinking-indicator')).toBeVisible({ timeout: 800 });

  // ...and the location still goes with the request once it arrives
  const request = await page.waitForRequest((r) => r.url().includes('/chat/stream') && r.method() === 'POST', { timeout: 5000 });
  expect(request.postData() ?? '').toContain('50.08');
  await expect(page.locator('.message.assistant:not(.streaming)')).toBeVisible({ timeout: 15000 });
});
