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
    await expect(popup.locator('.settings-label').first()).toHaveText('Appearance');
    await expect(popup.locator('.settings-label').nth(1)).toHaveText('Todoist Integration');
    await expect(popup.locator('.settings-label').nth(2)).toHaveText('Custom Instructions');
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

test.describe('Color Scheme', () => {
  // Clear localStorage before each test to ensure clean state
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.removeItem('ai-chatbot-color-scheme');
    });
  });

  test('shows color scheme options in settings popup', async ({ page }) => {
    await page.reload();
    await page.waitForSelector('#user-info');

    // Open settings popup
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');

    // Verify color scheme options are visible
    const options = page.locator('.settings-color-scheme-option');
    await expect(options).toHaveCount(3);

    // Verify labels
    await expect(options.nth(0).locator('.settings-color-scheme-label')).toHaveText('Light');
    await expect(options.nth(1).locator('.settings-color-scheme-label')).toHaveText('Dark');
    await expect(options.nth(2).locator('.settings-color-scheme-label')).toHaveText('System');
  });

  test('system is selected by default', async ({ page }) => {
    await page.reload();
    await page.waitForSelector('#user-info');

    // Open settings popup
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');

    // Verify system option is selected
    const systemOption = page.locator('.settings-color-scheme-option[data-color-scheme="system"]');
    await expect(systemOption).toHaveClass(/selected/);
  });

  test('switches to light theme when clicking Light option', async ({ page }) => {
    await page.reload();
    await page.waitForSelector('#user-info');

    // Open settings popup
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');

    // Click Light option
    await page.locator('.settings-color-scheme-option[data-color-scheme="light"]').click();

    // Verify light theme is applied
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');

    // Verify Light option is now selected
    const lightOption = page.locator('.settings-color-scheme-option[data-color-scheme="light"]');
    await expect(lightOption).toHaveClass(/selected/);
  });

  test('switches to dark theme when clicking Dark option', async ({ page }) => {
    // First set to light theme via localStorage (beforeEach clears it, so we set it again)
    await page.evaluate(() => {
      localStorage.setItem('ai-chatbot-color-scheme', 'light');
    });
    await page.reload();
    await page.waitForSelector('#user-info');

    // Verify light theme is active
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');

    // Open settings popup
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');

    // Click Dark option
    await page.locator('.settings-color-scheme-option[data-color-scheme="dark"]').click();

    // Verify dark theme is applied (no data-theme attribute)
    await expect(page.locator('html')).not.toHaveAttribute('data-theme');

    // Verify Dark option is now selected
    const darkOption = page.locator('.settings-color-scheme-option[data-color-scheme="dark"]');
    await expect(darkOption).toHaveClass(/selected/);
  });

  test('persists theme selection across page reload', async ({ page }) => {
    await page.reload();
    await page.waitForSelector('#user-info');

    // Open settings popup and select light theme
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');
    await page.locator('.settings-color-scheme-option[data-color-scheme="light"]').click();

    // Close popup
    await page.keyboard.press('Escape');
    await expect(page.locator('#settings-popup')).toHaveClass(/hidden/);

    // Reload page
    await page.reload();
    await page.waitForSelector('#user-info');

    // Verify light theme is still active
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');

    // Open settings popup and verify Light is selected
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');
    const lightOption = page.locator('.settings-color-scheme-option[data-color-scheme="light"]');
    await expect(lightOption).toHaveClass(/selected/);
  });

  test('theme applies immediately without needing to save', async ({ page }) => {
    await page.reload();
    await page.waitForSelector('#user-info');

    // Open settings popup
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');

    // Click Light option - theme should apply immediately
    await page.locator('.settings-color-scheme-option[data-color-scheme="light"]').click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');

    // Close popup without clicking save
    await page.keyboard.press('Escape');

    // Theme should still be applied
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  });

  test('theme affects visual appearance', async ({ page }) => {
    await page.reload();
    await page.waitForSelector('#user-info');

    // Open settings and select dark theme to ensure consistent starting point
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');
    await page.locator('.settings-color-scheme-option[data-color-scheme="dark"]').click();
    await page.keyboard.press('Escape');

    // Get dark theme background color
    const darkBg = await page.locator('body').evaluate((el) => {
      return window.getComputedStyle(el).backgroundColor;
    });

    // Switch to light theme
    await page.locator('#settings-btn').click();
    await page.waitForSelector('#settings-popup:not(.hidden)');
    await page.locator('.settings-color-scheme-option[data-color-scheme="light"]').click();

    // Get light theme background color
    const lightBg = await page.locator('body').evaluate((el) => {
      return window.getComputedStyle(el).backgroundColor;
    });

    // Verify background colors are different
    expect(darkBg).not.toBe(lightBg);
  });
});
