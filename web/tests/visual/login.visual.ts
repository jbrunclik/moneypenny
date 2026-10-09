/**
 * Visual regression tests for login screen
 *
 * These tests verify the login overlay appearance.
 * Since E2E tests bypass auth, we directly show the login overlay via DOM manipulation.
 */
import { test, expect } from '../global-setup';

test.describe('Visual: Login Screen', () => {
  test('login overlay - desktop', async ({ page }) => {
    await page.goto('/');

    // Wait for app to initialize
    await page.waitForSelector('#app');

    // Show login overlay by removing the hidden class
    await page.evaluate(() => {
      const overlay = document.getElementById('login-overlay');
      if (overlay) {
        overlay.classList.remove('hidden');
      }
    });

    // Wait for any transitions
    await page.waitForTimeout(100);

    await expect(page).toHaveScreenshot('login-overlay-desktop.png', {
      fullPage: true,
    });
  });

  test('login overlay - sign-in unavailable', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#app');

    // The state renderGoogleButton (auth/google.ts) shows when sign-in is
    // configured but Google's script never loaded - keep in sync with it
    await page.evaluate(() => {
      document.getElementById('login-overlay')?.classList.remove('hidden');
      const btn = document.getElementById('google-login-btn');
      if (btn) {
        btn.innerHTML = `
          <div class="login-unavailable" role="alert">
            <p>Sign-in couldn’t load. Check your connection and try again.</p>
            <button type="button" class="btn btn-secondary login-retry-btn">Retry</button>
          </div>
        `;
      }
    });
    await page.waitForTimeout(100);

    await expect(page.locator('.login-box')).toHaveScreenshot('login-overlay-unavailable.png');
  });

  test('login overlay - mobile', async ({ page }) => {
    // Set mobile viewport
    await page.setViewportSize({ width: 375, height: 812 });

    await page.goto('/');

    // Wait for app to initialize
    await page.waitForSelector('#app');

    // Show login overlay by removing the hidden class
    await page.evaluate(() => {
      const overlay = document.getElementById('login-overlay');
      if (overlay) {
        overlay.classList.remove('hidden');
      }
    });

    // Wait for any transitions
    await page.waitForTimeout(100);

    await expect(page).toHaveScreenshot('login-overlay-mobile.png', {
      fullPage: true,
    });
  });
});
