/**
 * E2E tests for settings popup and custom instructions
 */
import { test, expect } from '../global-setup';

test.describe('Settings', () => {
  test('settings button is visible in sidebar', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#user-info');

    const settingsBtn = page.locator('#settings-btn');
    await expect(settingsBtn).toBeVisible();
    await expect(settingsBtn).toHaveAttribute('title', 'Settings');
  });

  test('opens settings popup when clicking settings button', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#user-info');

    // Click settings button
    await page.locator('#settings-btn').click();

    // Wait for popup to appear
    await page.waitForSelector('#settings-popup:not(.hidden)');

    // Verify popup content
    const popup = page.locator('#settings-popup');
    await expect(popup).toBeVisible();
    await expect(popup.locator('h3')).toHaveText('Settings');
    await expect(popup.locator('.settings-label')).toHaveText('Custom Instructions');
    await expect(popup.locator('#custom-instructions')).toBeVisible();
    await expect(popup.locator('.settings-save-btn')).toBeVisible();
  });

  test('closes settings popup when clicking close button', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#user-info');

    // Open settings popup
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');

    // Click close button
    await page.locator('#settings-popup .info-popup-close').click();

    // Verify popup is hidden
    await expect(page.locator('#settings-popup')).toHaveClass(/hidden/);
  });

  test('closes settings popup when clicking backdrop', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#user-info');

    // Open settings popup
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');

    // Click on backdrop (the popup container itself)
    await page.locator('#settings-popup').click({ position: { x: 10, y: 10 } });

    // Verify popup is hidden
    await expect(page.locator('#settings-popup')).toHaveClass(/hidden/);
  });

  test('closes settings popup when pressing Escape', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#user-info');

    // Open settings popup
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');

    // Press Escape
    await page.keyboard.press('Escape');

    // Verify popup is hidden
    await expect(page.locator('#settings-popup')).toHaveClass(/hidden/);
  });

  test('saves custom instructions', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#user-info');

    // Open settings popup
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');

    // Enter custom instructions
    const textarea = page.locator('#custom-instructions');
    await textarea.fill('Respond in Czech.');

    // Click save
    await page.locator('.settings-save-btn').click();

    // Wait for popup to close and toast to appear
    await expect(page.locator('#settings-popup')).toHaveClass(/hidden/);

    // Re-open popup and verify instructions were saved
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');

    await expect(page.locator('#custom-instructions')).toHaveValue('Respond in Czech.');
  });

  test('shows character count', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#user-info');

    // Open settings popup
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');

    // Verify initial character count
    await expect(page.locator('.settings-char-count')).toHaveText('0/2000');

    // Enter some text
    const textarea = page.locator('#custom-instructions');
    await textarea.fill('Hello');

    // Verify character count updated
    await expect(page.locator('.settings-char-count')).toHaveText('5/2000');
  });

  test('shows warning when approaching character limit', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#user-info');

    // Open settings popup
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');

    // Enter text that's over 90% of limit
    const textarea = page.locator('#custom-instructions');
    await textarea.fill('x'.repeat(1850));

    // Verify warning class is applied
    await expect(page.locator('.settings-char-count')).toHaveClass(/warning/);
  });

  test('clears custom instructions with empty save', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#user-info');

    // First, set some instructions
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');
    await page.locator('#custom-instructions').fill('Be concise.');
    await page.locator('.settings-save-btn').click();
    await expect(page.locator('#settings-popup')).toHaveClass(/hidden/);

    // Now clear them
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');
    await page.locator('#custom-instructions').fill('');
    await page.locator('.settings-save-btn').click();
    await expect(page.locator('#settings-popup')).toHaveClass(/hidden/);

    // Verify they were cleared
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');
    await expect(page.locator('#custom-instructions')).toHaveValue('');
  });
});
