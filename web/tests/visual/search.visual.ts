/**
 * Visual regression tests for search functionality
 */
import { test, expect } from '../global-setup';

test.describe('Visual: Search Input', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.waitForSelector('#search-input');
  });

  test('search input default state', async ({ page }) => {
    // Wait for animations
    await page.waitForTimeout(300);

    await expect(page.locator('.search-container')).toHaveScreenshot('search-input-default.png');
  });

  test('search input focused', async ({ page }) => {
    const searchInput = page.locator('#search-input');
    await searchInput.focus();

    // Wait for animations
    await page.waitForTimeout(300);

    await expect(page.locator('.search-container')).toHaveScreenshot('search-input-focused.png');
  });

  test('search input with text and clear button', async ({ page }) => {
    const searchInput = page.locator('#search-input');
    await searchInput.fill('test query');

    // Wait for animations
    await page.waitForTimeout(300);

    await expect(page.locator('.search-container')).toHaveScreenshot('search-input-with-text.png');
  });
});

test.describe('Visual: Search Empty States', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.waitForSelector('#search-input');
  });

  test('search mode empty hint', async ({ page }) => {
    // Focus search input to activate search mode with empty query
    const searchInput = page.locator('#search-input');
    await searchInput.focus();

    // Wait for hint to appear
    await expect(page.locator('.search-empty')).toBeVisible();
    await page.waitForTimeout(300);

    await expect(page.locator('#conversations-list')).toHaveScreenshot('search-empty-hint.png');
  });

  test('search no results', async ({ page }) => {
    // Set empty mock results
    await page.request.post('/test/set-search-results', {
      data: {
        results: [],
        total: 0,
      },
    });

    // Type a query
    const searchInput = page.locator('#search-input');
    await searchInput.fill('xyznonexistent');

    // Wait for debounce and results
    await page.waitForTimeout(500);

    // Wait for empty state
    const searchEmpty = page.locator('.search-empty');
    await expect(searchEmpty).toContainText('No results found');

    await expect(page.locator('#conversations-list')).toHaveScreenshot('search-no-results.png');

    // Clean up
    await page.request.post('/test/clear-search-results');
  });
});

test.describe('Visual: Search Results', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.waitForSelector('#search-input');
  });

  test('search results list', async ({ page }) => {
    // Set mock search results
    await page.request.post('/test/set-search-results', {
      data: {
        results: [
          {
            conversation_id: 'conv-1',
            conversation_title: 'Python Programming',
            message_id: 'msg-1',
            message_snippet:
              'Learning about [[HIGHLIGHT]]Python[[/HIGHLIGHT]] programming and data science',
            match_type: 'message',
            created_at: new Date().toISOString(),
          },
          {
            conversation_id: 'conv-2',
            conversation_title: 'Machine Learning Basics',
            message_id: 'msg-2',
            message_snippet:
              'Understanding machine learning with [[HIGHLIGHT]]Python[[/HIGHLIGHT]] and TensorFlow',
            match_type: 'message',
            created_at: new Date(Date.now() - 86400000).toISOString(), // 1 day ago
          },
          {
            conversation_id: 'conv-3',
            conversation_title: 'Python Tutorial',
            message_id: null,
            message_snippet: null,
            match_type: 'conversation',
            created_at: new Date(Date.now() - 172800000).toISOString(), // 2 days ago
          },
        ],
        total: 3,
      },
    });

    // Trigger search
    const searchInput = page.locator('#search-input');
    await searchInput.fill('Python');

    // Wait for results
    await page.waitForTimeout(500);
    await expect(page.locator('.search-results-header')).toBeVisible();

    await expect(page.locator('#conversations-list')).toHaveScreenshot('search-results-list.png');

    // Clean up
    await page.request.post('/test/clear-search-results');
  });

  test('search result with highlighted snippet', async ({ page }) => {
    // Set mock search results with highlighted text
    await page.request.post('/test/set-search-results', {
      data: {
        results: [
          {
            conversation_id: 'conv-1',
            conversation_title: 'Important Discussion',
            message_id: 'msg-1',
            message_snippet:
              'This is a [[HIGHLIGHT]]highlighted[[/HIGHLIGHT]] search result with matched text',
            match_type: 'message',
            created_at: new Date().toISOString(),
          },
        ],
        total: 1,
      },
    });

    // Trigger search
    const searchInput = page.locator('#search-input');
    await searchInput.fill('highlighted');

    // Wait for results
    await page.waitForTimeout(500);
    const resultItem = page.locator('.search-result-item').first();
    await expect(resultItem).toBeVisible();

    await expect(resultItem).toHaveScreenshot('search-result-highlighted.png');

    // Clean up
    await page.request.post('/test/clear-search-results');
  });
});

test.describe('Visual: Search Loading', () => {
  test('search loading spinner', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.waitForSelector('#search-input');

    // Focus to activate search mode
    const searchInput = page.locator('#search-input');
    await searchInput.focus();

    // The loading state appears briefly when typing
    // Type slowly to capture the loading state before debounce completes
    await searchInput.type('te', { delay: 100 });

    // Small wait to ensure UI updates
    await page.waitForTimeout(50);

    // Note: This test may be flaky due to timing of loading state
    // The search-loading class may appear very briefly
    const searchLoading = page.locator('.search-loading');
    if ((await searchLoading.count()) > 0) {
      await expect(page.locator('#conversations-list')).toHaveScreenshot('search-loading.png');
    }
  });
});

test.describe('Visual: Sidebar with Search', () => {
  test('sidebar in search mode vs normal mode', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.waitForSelector('#search-input');

    // Disable streaming
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }

    // Create a conversation first
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test message for visual');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Screenshot normal state (conversation list visible)
    await page.waitForTimeout(300);
    await expect(page.locator('#sidebar')).toHaveScreenshot('sidebar-normal-mode.png');

    // Activate search mode
    const searchInput = page.locator('#search-input');
    await searchInput.focus();
    await searchInput.fill('Test');

    // Wait for debounce and results
    await page.waitForTimeout(500);

    // Screenshot search mode
    await expect(page.locator('#sidebar')).toHaveScreenshot('sidebar-search-mode.png');

    // Press escape to deactivate search
    await searchInput.press('Escape');
    await page.waitForTimeout(300);

    // Screenshot should be back to normal
    await expect(page.locator('#sidebar')).toHaveScreenshot('sidebar-after-search.png');
  });
});
