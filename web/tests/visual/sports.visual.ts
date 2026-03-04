/**
 * Visual regression tests for Sports Training feature
 */
import { test, expect } from '../global-setup';

const SAMPLE_PROGRAMS = [
  {
    id: 'pushups',
    name: 'Push-ups',
    emoji: '\uD83D\uDCAA',
    created_at: '2026-01-01T00:00:00',
  },
  {
    id: 'running',
    name: 'Morning Run',
    emoji: '\uD83C\uDFC3',
    created_at: '2026-01-15T00:00:00',
  },
];

test.describe('Visual: Sports Sidebar Entry', () => {
  test('sports entry default state', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.sports-entry');
    await page.waitForTimeout(300);

    await expect(page.locator('.sidebar')).toHaveScreenshot('sports-entry-default.png');
  });

  test('sports entry hover state', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.sports-entry');

    await page.locator('.sports-entry').hover();
    await page.waitForTimeout(200);

    await expect(page.locator('.sidebar')).toHaveScreenshot('sports-entry-hover.png');
  });

  test('sports entry active state', async ({ page }) => {
    await page.goto('/#/sports');
    await page.waitForSelector('.sports-entry.active');
    await page.waitForTimeout(300);

    await expect(page.locator('.sidebar')).toHaveScreenshot('sports-entry-active.png');
  });

  test('sidebar nav row with three entries', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.sidebar-nav-row');
    await page.waitForTimeout(300);

    await expect(page.locator('.sidebar-nav-row')).toHaveScreenshot(
      'sidebar-nav-row-three-entries.png',
    );
  });
});

test.describe('Visual: Sports Programs List', () => {
  test('programs empty state', async ({ page }) => {
    await page.goto('/#/sports');
    await page.waitForSelector('.sports-programs-container');
    await page.waitForTimeout(300);

    await expect(page.locator('.main')).toHaveScreenshot('programs-empty.png');
  });

  test('programs with data', async ({ page }) => {
    await page.request.post('/test/set-sports-programs', {
      data: { programs: SAMPLE_PROGRAMS },
    });

    await page.goto('/#/sports');
    await page.waitForSelector('.sports-program-card');
    await page.waitForTimeout(300);

    await expect(page.locator('.main')).toHaveScreenshot('programs-with-data.png');
  });

  test('program card hover state', async ({ page }) => {
    await page.request.post('/test/set-sports-programs', {
      data: { programs: SAMPLE_PROGRAMS },
    });

    await page.goto('/#/sports');
    await page.waitForSelector('.sports-program-card');

    await page.locator('.sports-program-card').first().hover();
    await page.waitForTimeout(200);

    await expect(page.locator('.main')).toHaveScreenshot('program-card-hover.png');
  });
});

test.describe('Visual: New Program Modal', () => {
  test('new program modal', async ({ page }) => {
    await page.goto('/#/sports');
    await page.waitForSelector('.sports-add-btn');

    await page.locator('.sports-add-btn').click();
    await page.waitForSelector('.sports-modal-overlay');
    await page.waitForTimeout(200);

    await expect(page.locator('.sports-modal-overlay')).toHaveScreenshot('new-program-modal.png');
  });

  test('new program modal filled with emoji', async ({ page }) => {
    await page.goto('/#/sports');
    await page.waitForSelector('.sports-add-btn');

    await page.locator('.sports-add-btn').click();
    await page.waitForSelector('.sports-modal-overlay');

    // Open emoji popover and select a different emoji
    await page.locator('.sports-emoji-trigger').click();
    await page.waitForSelector('.sports-emoji-popover.open');
    await page.locator('.sports-emoji-option').nth(2).click();
    await page.locator('.sports-add-name').fill('Cycling');
    await page.waitForTimeout(200);

    await expect(page.locator('.sports-modal-overlay')).toHaveScreenshot('new-program-filled.png');
  });
});

test.describe('Visual: Program Chat Header', () => {
  test('program header default', async ({ page }) => {
    await page.request.post('/test/set-sports-programs', {
      data: { programs: SAMPLE_PROGRAMS },
    });

    await page.goto('/#/sports/pushups');
    await page.waitForSelector('.sports-program-header');
    await page.waitForTimeout(300);

    await expect(page.locator('.sports-program-header')).toHaveScreenshot(
      'program-header-default.png',
    );
  });

  test('program header reset hover', async ({ page }) => {
    await page.request.post('/test/set-sports-programs', {
      data: { programs: SAMPLE_PROGRAMS },
    });

    await page.goto('/#/sports/pushups');
    await page.waitForSelector('.sports-program-header');

    await page.locator('.sports-reset-btn').hover();
    await page.waitForTimeout(200);

    await expect(page.locator('.sports-program-header')).toHaveScreenshot(
      'program-header-reset-hover.png',
    );
  });
});

test.describe('Visual: Sports Mobile', () => {
  test.use({ viewport: { width: 375, height: 667 } });

  test('programs mobile view', async ({ page }) => {
    await page.request.post('/test/set-sports-programs', {
      data: { programs: SAMPLE_PROGRAMS },
    });

    await page.goto('/#/sports');
    await page.waitForSelector('.sports-program-card');
    await page.waitForTimeout(300);

    await expect(page.locator('.main')).toHaveScreenshot('programs-mobile.png');
  });

  test('program header mobile', async ({ page }) => {
    await page.request.post('/test/set-sports-programs', {
      data: { programs: SAMPLE_PROGRAMS },
    });

    await page.goto('/#/sports/pushups');
    await page.waitForSelector('.sports-program-header');
    await page.waitForTimeout(300);

    await expect(page.locator('.sports-program-header')).toHaveScreenshot(
      'program-header-mobile.png',
    );
  });
});
