/**
 * Visual regression tests for K/V Store (Data Management) page.
 */
import { test, expect } from '../global-setup';

// Timestamps are generated relative to the test run and sit mid-bucket
// ("Nmo ago"), so the rendered relative time is identical on every run.
// Fixed ISO dates here are a time bomb: the snapshot silently expires
// whenever wall-clock time crosses a bucket boundary.
const DAY_MS = 86_400_000;
const daysAgo = (days: number): string => new Date(Date.now() - days * DAY_MS).toISOString();

const MOCK_MEMORIES = [
  {
    id: 'mem-1',
    content: 'User prefers dark mode for all applications',
    category: 'preference',
    created_at: daysAgo(135),
    updated_at: daysAgo(135), // "4mo ago"
  },
  {
    id: 'mem-2',
    content: 'Works as a software engineer at a Prague-based company',
    category: 'fact',
    created_at: daysAgo(105),
    updated_at: daysAgo(105), // "3mo ago"
  },
  {
    id: 'mem-3',
    content: 'Currently learning Czech language, intermediate level',
    category: 'context',
    created_at: daysAgo(75),
    updated_at: daysAgo(75), // "2mo ago"
  },
  {
    id: 'mem-4',
    content: 'Training for Prague Half Marathon in April 2026',
    category: 'goal',
    created_at: daysAgo(45),
    updated_at: daysAgo(45), // "1mo ago"
  },
];

const MOCK_NAMESPACES = [
  { namespace: 'fitness', key_count: 2 },
  { namespace: 'lang:czech', key_count: 3 },
  // Long mono nowrap name - regression guard: this used to blow the
  // container past the mobile viewport and widen every card on the page
  { namespace: 'agent:81c0fe14-0cbf-48a1-a5b3-8266bc3b370d', key_count: 2 },
  { namespace: 'news', key_count: 2 },
];

const MOCK_KEYS: Record<string, { key: string; value: string }[]> = {
  fitness: [
    { key: 'goals', value: '{"monthly_km": 100, "target_pace": "5:15/km", "race": {"name": "Prague Half Marathon", "date": "2026-04-05"}}' },
    { key: 'weekly_summary', value: '{"week": "2026-W09", "runs": 3, "total_km": 22.5, "avg_pace": "5:32/km", "calories": 1850}' },
  ],
  'lang:czech': [
    { key: 'daily_streak', value: '{"current": 7, "longest": 14}' },
    { key: 'difficult_words', value: '{"words": ["zahrádka", "příležitost", "následující"]}' },
    { key: 'vocabulary_progress', value: '{"total_words": 150, "mastered": 42, "learning": 78, "new": 30}' },
  ],
  news: [
    { key: 'latest_headlines', value: '{"source": "Reuters", "articles": [{"title": "Tech stocks rally on AI optimism"}, {"title": "Central banks hold rates steady"}]}' },
    { key: 'preferences', value: '{"topics": ["technology", "finance", "science"], "language": "en", "max_articles": 10}' },
  ],
};

async function setupStoragePage(page: import('@playwright/test').Page, options?: {
  memories?: typeof MOCK_MEMORIES | null;
  namespaces?: typeof MOCK_NAMESPACES | null;
  keys?: typeof MOCK_KEYS | null;
}) {
  const mems = options?.memories !== undefined ? options.memories : MOCK_MEMORIES;
  const ns = options?.namespaces !== undefined ? options.namespaces : MOCK_NAMESPACES;
  const ks = options?.keys !== undefined ? options.keys : MOCK_KEYS;

  if (mems !== null) {
    await page.request.post('/test/set-memories-data', {
      data: { memories: mems },
    });
  }
  if (ns !== null) {
    await page.request.post('/test/set-kv-store-data', {
      data: { namespaces: ns, keys: ks },
    });
  }
}

test.describe('Visual: Storage Page - Desktop', () => {
  test('storage page with data', async ({ page }) => {
    await setupStoragePage(page);

    await page.goto('/#/storage');
    await page.waitForSelector('.kv-store');
    await page.waitForTimeout(300);

    await expect(page.locator('.main')).toHaveScreenshot('storage-page-with-data.png');
  });

  test('storage page empty state', async ({ page }) => {
    await setupStoragePage(page, {
      memories: [],
      namespaces: [],
    });

    await page.goto('/#/storage');
    await page.waitForSelector('.kv-store');
    await page.waitForTimeout(300);

    await expect(page.locator('.main')).toHaveScreenshot('storage-page-empty.png');
  });

  test('storage page memories only', async ({ page }) => {
    await setupStoragePage(page, {
      namespaces: [],
    });

    await page.goto('/#/storage');
    await page.waitForSelector('.kv-store');
    await page.waitForTimeout(300);

    await expect(page.locator('.main')).toHaveScreenshot('storage-page-memories-only.png');
  });

  test('storage page kv only', async ({ page }) => {
    await setupStoragePage(page, {
      memories: [],
    });

    await page.goto('/#/storage');
    await page.waitForSelector('.kv-store');
    await page.waitForTimeout(300);

    await expect(page.locator('.main')).toHaveScreenshot('storage-page-kv-only.png');
  });

  test('expanded namespace shows keys with JSON highlighting', async ({ page }) => {
    await setupStoragePage(page);

    await page.goto('/#/storage');
    await page.waitForSelector('.kv-store');
    await page.waitForTimeout(300);

    // Expand the fitness namespace
    await page.locator('.kv-namespace-title-row').first().click();
    await page.waitForSelector('.kv-keys-list');
    await page.waitForTimeout(300);

    await expect(page.locator('.main')).toHaveScreenshot('storage-page-expanded-namespace.png');
  });

  test('memory delete confirmation dialog', async ({ page }) => {
    await setupStoragePage(page);

    await page.goto('/#/storage');
    await page.waitForSelector('.kv-store');
    await page.waitForTimeout(300);

    // Click first memory delete button
    await page.locator('.memory-delete').first().click();
    await page.waitForSelector('.modal-container:not(.modal-hidden)');
    await page.waitForTimeout(200);

    await expect(page).toHaveScreenshot('storage-page-delete-confirm.png', { fullPage: true });
  });
});

test.describe('Visual: Storage Page - Mobile', () => {
  test.use({ viewport: { width: 375, height: 667 } });

  test('storage page mobile view', async ({ page }) => {
    await setupStoragePage(page);

    await page.goto('/#/storage');
    await page.waitForSelector('.kv-store');
    await page.waitForTimeout(300);

    await expect(page.locator('.main')).toHaveScreenshot('storage-page-mobile.png');
  });

  test('storage page mobile expanded namespace', async ({ page }) => {
    await setupStoragePage(page);

    await page.goto('/#/storage');
    await page.waitForSelector('.kv-store');
    await page.waitForTimeout(300);

    // Expand the fitness namespace
    await page.locator('.kv-namespace-title-row').first().click();
    await page.waitForSelector('.kv-keys-list');
    await page.waitForTimeout(300);

    await expect(page.locator('.main')).toHaveScreenshot('storage-page-mobile-expanded.png');
  });
});
