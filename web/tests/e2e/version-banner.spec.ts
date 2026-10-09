/**
 * E2E tests for the version-update banner's resting (hidden) state.
 */
import { test, expect } from '../global-setup';

test.describe('Version banner', () => {
  test('hidden banner casts no shadow and is out of the tab order', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    const banner = page.locator('.version-banner');
    await expect(banner).not.toHaveClass(/visible/);
    // Parked above the viewport: its shadow bled a dark band onto every screen
    const style = await banner.evaluate((el) => {
      const cs = getComputedStyle(el);
      return { boxShadow: cs.boxShadow, visibility: cs.visibility };
    });
    expect(style.boxShadow).toBe('none');
    // ...and its Reload/Dismiss buttons were keyboard-focusable off-screen
    expect(style.visibility).toBe('hidden');
  });
});
