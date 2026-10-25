/**
 * E2E tests for the admin page and the spend warning banner (S12). The E2E
 * server lists the auth-bypass user in ADMIN_EMAILS.
 */
import type { Page } from '@playwright/test';
import { test, expect } from '../global-setup';

async function seedSpend(page: Page, usd: number): Promise<void> {
  const response = await page.request.post('/test/seed', {
    data: {
      conversations: [
        {
          title: 'Busy day',
          messages: [
            { role: 'user', content: 'Plan everything' },
            { role: 'assistant', content: 'Done', cost_usd: usd },
          ],
        },
      ],
    },
  });
  expect(response.ok()).toBe(true);
}

async function openUserMenu(page: Page): Promise<void> {
  await page.click('#user-menu-btn');
  await expect(page.locator('.user-menu')).toBeVisible();
}

test.describe('Admin page', () => {
  test('opens from the user menu and shows every section', async ({ page }) => {
    await seedSpend(page, 1.5);
    await page.goto('/');
    await openUserMenu(page);
    await page.click('#admin-btn');

    const adminPage = page.locator('.admin-page');
    await expect(adminPage).toBeVisible();
    await expect(adminPage.locator('.admin-user-row')).not.toHaveCount(0);
    for (const title of ['Spend', 'Agents', 'Web search this period', 'Responses (7 days)', 'System']) {
      await expect(adminPage.locator('h2', { hasText: title })).toBeVisible();
    }
    await expect(adminPage.locator('.admin-chart rect')).toHaveCount(30);
  });

  test('closes with Escape and with Back', async ({ page }) => {
    await page.goto('/');
    await openUserMenu(page);
    await page.click('#admin-btn');
    await expect(page.locator('.admin-page')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('.admin-page')).toHaveCount(0);

    await openUserMenu(page);
    await page.click('#admin-btn');
    await page.click('.admin-back');
    await expect(page.locator('.admin-page')).toHaveCount(0);
  });
});

test.describe('Spend warning banner', () => {
  test('appears past the daily threshold and stays dismissed for the day', async ({ page }) => {
    await seedSpend(page, 12);
    await page.goto('/');
    const banner = page.locator('.spend-banner');
    await expect(banner).toContainText('let the admin know');

    await banner.locator('.spend-banner-dismiss').click();
    await expect(banner).toHaveCount(0);
    // A dismissed day skips the status call entirely: wait for the page's
    // own startup instead, then check the banner stayed away
    await page.reload();
    await expect(page.locator('.user-cost')).not.toHaveText('—');
    await expect(page.locator('.spend-banner')).toHaveCount(0);
  });

  test('stays away under the threshold', async ({ page }) => {
    await seedSpend(page, 2);
    // Assert only after the status answer arrived, or the check is vacuous
    const status = page.waitForResponse('**/api/users/me/spend-status');
    await page.goto('/');
    const body = await (await status).json();
    expect(body.over_threshold).toBe(false);
    await expect(page.locator('.spend-banner')).toHaveCount(0);
  });
});
