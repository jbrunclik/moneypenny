/**
 * Visual regression tests for the admin page and the spend warning banner
 * (S12). The overview and spend status are fixed JSON, so the snapshots
 * don't depend on the database or the clock.
 */
import type { Page } from '@playwright/test';
import { test, expect } from '../global-setup';

const money = (usd: number) => ({ usd, formatted: `${(usd * 23).toFixed(2)} Kč` });

const OVERVIEW = {
  generated_at: '2026-10-25T15:00:00',
  currency: 'CZK',
  spend: {
    today: money(14.2),
    month: money(182.5),
    threshold: money(10),
    users: [
      { name: 'Jana', today: money(12.1), month: money(71.3), month_chats: 42, month_turns: 518, over_threshold: true },
      { name: 'Petr', today: money(1.6), month: money(64.9), month_chats: 37, month_turns: 460, over_threshold: false },
      { name: 'Ema', today: money(0.5), month: money(46.3), month_chats: 19, month_turns: 233, over_threshold: false },
    ],
    daily: Array.from({ length: 30 }, (_, i) => ({
      date: `2026-10-${String(i + 1).padStart(2, '0')}`,
      amount: money([3, 5, 8, 4, 6, 7, 2][i % 7] + (i === 29 ? 9 : 0)),
    })),
    by_feature: [
      { name: 'chat', amount: money(120.4) },
      { name: 'agents', amount: money(38.2) },
      { name: 'planner', amount: money(14.1) },
      { name: 'language', amount: money(9.8) },
    ],
    by_model: [
      { name: 'gemini-3.8-flash', amount: money(140.3) },
      { name: 'gemini-3.1-pro-preview', amount: money(42.2) },
    ],
  },
  agents: {
    runs_7d: 42,
    failed_7d: 2,
    pending_approvals: 1,
    recent_failures: [
      {
        agent_name: 'Daily Briefing',
        user_name: 'Jana',
        started_at: '2026-10-25T06:00:00',
        error: 'Calendar token expired - reconnect Google Calendar',
      },
    ],
  },
  search: {
    degraded_today: true,
    providers: [
      { provider: 'brave', configured: true, used: 1000, quota: 1000, available: false },
      { provider: 'tavily', configured: true, used: 845, quota: 1000, available: true },
      { provider: 'ddgs', configured: true, used: 0, quota: null, available: true },
    ],
  },
  quality: { turns_7d: 512, median_ms: 9400, p95_ms: 41200, tool_error_rate: 0.031 },
  system: {
    version: '072db55d',
    database_bytes: 258785280,
    files_bytes: 516935680,
    last_backup_at: '2026-10-25T02:26:00',
    latest_migration: '0068_unique_planner_conversation',
    users: 4,
  },
  browser_errors: [
    {
      kind: 'unhandled_rejection',
      message: "TypeError: Cannot read properties of undefined (reading 'scope')",
      stack: "TypeError: Cannot read properties of undefined (reading 'scope')\n    at registerPush (main.js:2:5186)",
      path: '#/settings',
      app_version: '072db55d',
      count: 14,
      users: 3,
      last_seen: '2026-10-25T14:02:00',
    },
    {
      kind: 'logged',
      message: '[sync] Sync failed: Network error. Please check your connection.',
      stack: null,
      path: '#/chat/4f2a',
      app_version: '072db55d',
      count: 3,
      users: 1,
      last_seen: '2026-10-24T21:40:00',
    },
  ],
};

async function openAdmin(page: Page): Promise<void> {
  await page.route('**/api/admin/overview', (route) => route.fulfill({ json: OVERVIEW }));
  await page.goto('/');
  await page.click('#user-menu-btn');
  await page.click('#admin-btn');
  await expect(page.locator('.admin-user-row')).toHaveCount(3);
}

async function showBanner(page: Page): Promise<void> {
  await page.route('**/api/users/me/spend-status', (route) =>
    route.fulfill({ json: { today: money(12.4), threshold_usd: 10, over_threshold: true } })
  );
  await page.goto('/');
  await expect(page.locator('.spend-banner')).toBeVisible();
}

test.describe('Visual: Admin - Desktop', () => {
  test('admin page', async ({ page }) => {
    await openAdmin(page);
    await expect(page.locator('.admin-page')).toHaveScreenshot('admin-page.png');
  });

  test('spend warning banner', async ({ page }) => {
    await showBanner(page);
    await expect(page.locator('.spend-banner')).toHaveScreenshot('spend-banner.png');
  });
});

test.describe('Visual: Admin - Mobile', () => {
  test.use({ viewport: { width: 375, height: 667 } });

  test('admin page mobile', async ({ page }) => {
    await page.route('**/api/admin/overview', (route) => route.fulfill({ json: OVERVIEW }));
    await page.goto('/');
    await page.click('#menu-btn');
    await page.click('#user-menu-btn');
    await page.click('#admin-btn');
    await expect(page.locator('.admin-user-row')).toHaveCount(3);
    await expect(page.locator('.admin-page')).toHaveScreenshot('admin-page-mobile.png');
  });

  test('spend warning banner mobile', async ({ page }) => {
    await showBanner(page);
    await expect(page).toHaveScreenshot('spend-banner-mobile.png');
  });
});
