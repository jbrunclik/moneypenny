/**
 * E2E tests for login screen behavior
 *
 * These tests verify the login overlay behavior and structure.
 * Since E2E tests bypass auth by default, we show the login overlay
 * via DOM manipulation for testing.
 */
import { test, expect } from '../global-setup';

test.describe('Login Screen', () => {
  test('login overlay covers entire screen', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#app');

    // Show login overlay
    await page.evaluate(() => {
      const overlay = document.getElementById('login-overlay');
      if (overlay) {
        overlay.classList.remove('hidden');
      }
    });

    // Verify overlay is visible and covers the viewport
    const overlay = page.locator('#login-overlay');
    await expect(overlay).toBeVisible();

    // Check overlay dimensions match viewport
    const overlayBox = await overlay.boundingBox();
    const viewport = page.viewportSize();

    expect(overlayBox).not.toBeNull();
    expect(overlayBox!.width).toBe(viewport!.width);
    expect(overlayBox!.height).toBe(viewport!.height);
    expect(overlayBox!.x).toBe(0);
    expect(overlayBox!.y).toBe(0);
  });

  test('login overlay shows correct content', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#app');

    // Show login overlay
    await page.evaluate(() => {
      const overlay = document.getElementById('login-overlay');
      if (overlay) {
        overlay.classList.remove('hidden');
      }
    });

    // Check login box content
    const loginBox = page.locator('.login-box');
    await expect(loginBox).toBeVisible();

    // Check heading
    const heading = loginBox.locator('h2');
    await expect(heading).toHaveText('AI Chatbot');

    // Check subtitle
    const subtitle = loginBox.locator('p');
    await expect(subtitle).toHaveText('Sign in to continue');

    // Check Google button container exists (may be empty in test mode, but element should exist)
    const googleBtn = page.locator('#google-login-btn');
    // Use count() instead of toBeVisible since the container exists but may not have content in test mode
    await expect(googleBtn).toHaveCount(1);
  });

  test('login overlay blocks interaction with app behind', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#app');

    // Show login overlay
    await page.evaluate(() => {
      const overlay = document.getElementById('login-overlay');
      if (overlay) {
        overlay.classList.remove('hidden');
      }
    });

    // Try to click on an element that would be behind the overlay
    // The overlay should capture the click instead
    const overlay = page.locator('#login-overlay');
    const newChatBtn = page.locator('#new-chat-btn');

    // Verify overlay is on top
    const overlayZIndex = await overlay.evaluate((el) => {
      return parseInt(getComputedStyle(el).zIndex);
    });
    expect(overlayZIndex).toBeGreaterThan(0);

    // The new chat button should not be accessible (behind the overlay)
    // We verify this by checking the overlay has pointer-events: auto (default)
    const overlayPointerEvents = await overlay.evaluate((el) => {
      return getComputedStyle(el).pointerEvents;
    });
    expect(overlayPointerEvents).toBe('auto');
  });

  test('login overlay hides when hidden class is added', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#app');

    // First show, then hide the overlay
    await page.evaluate(() => {
      const overlay = document.getElementById('login-overlay');
      if (overlay) {
        overlay.classList.remove('hidden');
      }
    });

    const overlay = page.locator('#login-overlay');
    await expect(overlay).toBeVisible();

    // Now hide it
    await page.evaluate(() => {
      const overlay = document.getElementById('login-overlay');
      if (overlay) {
        overlay.classList.add('hidden');
      }
    });

    await expect(overlay).toBeHidden();
  });

  test('login overlay is hidden by default when authenticated', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#app');

    // In E2E test mode, auth is bypassed so the overlay should be hidden
    const overlay = page.locator('#login-overlay');
    await expect(overlay).toBeHidden();
  });

  test('login overlay uses theme background', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#app');

    // Show login overlay
    await page.evaluate(() => {
      const overlay = document.getElementById('login-overlay');
      if (overlay) {
        overlay.classList.remove('hidden');
      }
    });

    const overlay = page.locator('#login-overlay');

    // Check that background color is set (uses CSS variable --bg-primary)
    // The exact color depends on theme, but it should be a solid color (not transparent)
    const bgColor = await overlay.evaluate((el) => {
      return getComputedStyle(el).backgroundColor;
    });
    // Background should not be transparent
    expect(bgColor).not.toBe('transparent');
    expect(bgColor).not.toBe('rgba(0, 0, 0, 0)');
    // Should be an rgb/rgba color
    expect(bgColor).toMatch(/^rgb/);
  });

  test('login overlay is centered on mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });

    await page.goto('/');
    await page.waitForSelector('#app');

    // Show login overlay
    await page.evaluate(() => {
      const overlay = document.getElementById('login-overlay');
      if (overlay) {
        overlay.classList.remove('hidden');
      }
    });

    const loginBox = page.locator('.login-box');
    await expect(loginBox).toBeVisible();

    // Check that login box is centered (roughly in the middle of the screen)
    const boxBounds = await loginBox.boundingBox();
    const viewport = page.viewportSize();

    expect(boxBounds).not.toBeNull();

    // Box should be horizontally centered (within a tolerance)
    const boxCenterX = boxBounds!.x + boxBounds!.width / 2;
    const viewportCenterX = viewport!.width / 2;
    expect(Math.abs(boxCenterX - viewportCenterX)).toBeLessThan(10);
  });
});
