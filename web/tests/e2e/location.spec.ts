/**
 * E2E tests for device location sharing (settings toggle + client_location on chat requests)
 */
import { test, expect } from '../global-setup';

test.describe('Location sharing', () => {
  test.use({
    geolocation: { latitude: 50.0813, longitude: 14.4135 },
    permissions: ['geolocation'],
  });

  test('settings toggle enables location sharing', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#user-info');

    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');

    const toggle = page.locator('#location-sharing-enabled');
    await expect(toggle).not.toBeChecked();

    // The checkbox input is visually hidden (styled toggle) - click its label
    await page.locator('label.toggle-label:has(#location-sharing-enabled)').click();
    await expect(toggle).toBeChecked();
    // Success toast confirms a fix was obtained (permission granted via test.use)
    await expect(
      page.locator('.toast-success', { hasText: 'Location sharing enabled' })
    ).toBeVisible();

    // Persisted per device
    const stored = await page.evaluate(() => localStorage.getItem('location_sharing_enabled'));
    expect(stored).toBe('true');
  });

  test('sends client_location with chat when sharing is enabled', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Enable sharing (set directly; toggle UX is covered above)
    await page.evaluate(() => localStorage.setItem('location_sharing_enabled', 'true'));

    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'what is near me?');

    const requestPromise = page.waitForRequest(
      (req) => req.url().includes('/chat/') && req.method() === 'POST'
    );
    await page.click('#send-btn');

    const request = await requestPromise;
    const body = request.postDataJSON() as {
      client_location?: { lat: number; lon: number; accuracy_m: number | null };
    };
    expect(body.client_location).toBeDefined();
    expect(body.client_location?.lat).toBeCloseTo(50.0813, 3);
    expect(body.client_location?.lon).toBeCloseTo(14.4135, 3);
  });

  test('omits client_location when sharing is disabled', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'hello');

    const requestPromise = page.waitForRequest(
      (req) => req.url().includes('/chat/') && req.method() === 'POST'
    );
    await page.click('#send-btn');

    const body = (await requestPromise).postDataJSON() as Record<string, unknown>;
    expect(body.client_location).toBeUndefined();
  });
});
