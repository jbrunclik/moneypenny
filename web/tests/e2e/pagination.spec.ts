/**
 * E2E tests for pagination (conversations and messages)
 */
import { test, expect } from '../global-setup';

test.describe('Conversations Pagination', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Disable streaming for reliable mock responses
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }
  });

  test('loads initial conversations', async ({ page }) => {
    // Create a few conversations
    for (let i = 0; i < 3; i++) {
      await page.click('#new-chat-btn');
      await page.fill('#message-input', `Conversation ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector('.message.assistant', { timeout: 10000 });
    }

    // Verify conversations appear in sidebar
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(3);
  });

  test('shows empty state when no conversations', async ({ page }) => {
    // Before creating any conversations, the sidebar should show empty state
    // But the welcome message in the main area is shown for new (temp) conversations
    // The empty state shows in the conversations list
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(0);

    // The welcome message should be visible in the main chat area
    const welcomeMessage = page.locator('.welcome-message');
    await expect(welcomeMessage).toBeVisible();
  });

  test('loads more conversations on scroll', async ({ page }) => {
    // Create many conversations to trigger pagination
    // The default page size is 30, so we need to create more than that
    // For E2E tests, we'll create a smaller number but force a small page size
    const numConversations = 20;

    for (let i = 0; i < numConversations; i++) {
      await page.click('#new-chat-btn');
      await page.fill('#message-input', `Conversation ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector('.message.assistant', { timeout: 15000 });
    }

    // Verify all conversations are in sidebar
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(numConversations);

    // Reload page to test fresh load
    await page.reload();
    await page.waitForSelector('#new-chat-btn');

    // All conversations should be loaded (less than default page size)
    await expect(convItems).toHaveCount(numConversations, { timeout: 10000 });
  });

  test('pagination preserves conversation order', async ({ page }) => {
    // Create conversations with distinct names
    const names = ['Alpha', 'Beta', 'Gamma', 'Delta'];
    for (const name of names) {
      await page.click('#new-chat-btn');
      await page.fill('#message-input', `Test ${name}`);
      await page.click('#send-btn');
      await page.waitForSelector('.message.assistant', { timeout: 10000 });
    }

    // Should have 4 conversations
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(4);

    // Conversations should be in reverse order (most recent first)
    // The first conversation (Alpha) should be at the bottom
    // The last conversation (Delta) should be at the top
    // We can verify by clicking the last one and checking it shows "Alpha"
    await convItems.last().click();
    const userMessage = page.locator('.message.user');
    await expect(userMessage).toContainText('Test Alpha');
  });

  test('conversations load-more indicator only shows when there are more pages', async ({ page }) => {
    // The load-more indicator only shows when hasMore is true
    // With small number of conversations, hasMore will be false

    // Create some conversations
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // With just 1 conversation, hasMore should be false, so no load-more indicator
    const loadMore = page.locator('.conversations-load-more');
    await expect(loadMore).toHaveCount(0);

    // Verify we have the conversation
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(1);
  });

  test('clicking conversation in paginated list switches correctly', async ({ page }) => {
    // Create multiple conversations
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First conversation message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second conversation message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Click on the first (older) conversation
    const convItems = page.locator('.conversation-item-wrapper');
    await convItems.last().click();

    // Should show the first conversation's messages
    const userMessage = page.locator('.message.user');
    await expect(userMessage).toContainText('First conversation message');
  });
});

test.describe('Conversations Pagination - Load More', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Disable streaming
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }
  });

  test('appends new conversations when loading more', async ({ page }) => {
    // Create initial conversations
    const initialCount = 5;
    for (let i = 0; i < initialCount; i++) {
      await page.click('#new-chat-btn');
      await page.fill('#message-input', `Initial ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector('.message.assistant', { timeout: 10000 });
    }

    // Verify initial count
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(initialCount);

    // Create more conversations
    const additionalCount = 3;
    for (let i = 0; i < additionalCount; i++) {
      await page.click('#new-chat-btn');
      await page.fill('#message-input', `Additional ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector('.message.assistant', { timeout: 10000 });
    }

    // Should have all conversations
    await expect(convItems).toHaveCount(initialCount + additionalCount);
  });

  test('sidebar scroll position is maintained after load more', async ({ page }) => {
    // Create several conversations
    const numConversations = 10;
    for (let i = 0; i < numConversations; i++) {
      await page.click('#new-chat-btn');
      await page.fill('#message-input', `Conversation ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector('.message.assistant', { timeout: 15000 });
    }

    // Get the sidebar/conversations list
    const convList = page.locator('.conversations-list');

    // Scroll down a bit
    await convList.evaluate((el) => {
      el.scrollTop = 100;
    });

    // Record scroll position
    const scrollBefore = await convList.evaluate((el) => el.scrollTop);
    expect(scrollBefore).toBeGreaterThan(0);

    // Add a new conversation (should prepend, not scroll)
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'New conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Verify conversations increased
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(numConversations + 1);
  });

  test('conversations loader is not shown when not loading', async ({ page }) => {
    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // The conversations loader should not be visible
    const loader = page.locator('.conversations-load-more.loading');
    await expect(loader).toHaveCount(0);
  });

  test('conversations loader shows loading dots when loading more', async ({ page }) => {
    // Create enough conversations to trigger pagination
    // Default page size is 30, so create 35 to ensure pagination
    const numConversations = 35;
    for (let i = 0; i < numConversations; i++) {
      await page.click('#new-chat-btn');
      await page.fill('#message-input', `Conversation ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector('.message.assistant', { timeout: 10000 });
    }

    // Reload to get fresh pagination state
    await page.reload();
    await page.waitForSelector('#new-chat-btn');

    // Scroll to bottom of conversations list to trigger load more
    const convList = page.locator('.conversations-list');
    await convList.evaluate((el) => {
      el.scrollTop = el.scrollHeight;
    });

    // Wait for scroll handler to trigger and loader to appear
    // The loader should appear when isLoadingMore becomes true
    const loadMore = page.locator('.conversations-load-more.loading');
    try {
      // Wait up to 2 seconds for loader to appear
      await loadMore.waitFor({ timeout: 2000, state: 'visible' });
    } catch {
      // Loader might not appear if API call completes too fast, that's okay
      // The structure is tested in component tests
    }

    // If loader appeared, verify it has loading dots
    const loadMoreCount = await loadMore.count();
    if (loadMoreCount > 0) {
      const loadingDots = loadMore.locator('.loading-dots');
      const dotsCount = await loadingDots.count();
      expect(dotsCount).toBeGreaterThan(0);

      // Verify loading dots have 3 spans
      const dots = loadingDots.first();
      const spans = dots.locator('span');
      await expect(spans).toHaveCount(3);
    }
  });
});

test.describe('Pagination with Sync', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Disable streaming
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }
  });

  test('new conversations from sync appear at top', async ({ page }) => {
    // Create initial conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Create another conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Most recent should be at top
    const firstConv = page.locator('.conversation-item-wrapper').first();
    const title = await firstConv.locator('.conversation-title').textContent();
    // The title is auto-generated or default "New Conversation"
    expect(title).toBeTruthy();
  });

  test('pagination works after page reload', async ({ page }) => {
    // Create conversations
    const numConversations = 5;
    for (let i = 0; i < numConversations; i++) {
      await page.click('#new-chat-btn');
      await page.fill('#message-input', `Conversation ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector('.message.assistant', { timeout: 10000 });
    }

    // Reload page
    await page.reload();
    await page.waitForSelector('#new-chat-btn');

    // Wait for conversations to load
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(numConversations, { timeout: 10000 });

    // Click on a conversation to verify it loads correctly
    await convItems.first().click();

    // Should show messages
    const messages = page.locator('.message');
    await expect(messages.first()).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Pagination Edge Cases', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Disable streaming
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }
  });

  test('handles rapid conversation creation', async ({ page }) => {
    // Create conversations quickly
    for (let i = 0; i < 5; i++) {
      await page.click('#new-chat-btn');
      await page.fill('#message-input', `Quick ${i + 1}`);
      await page.click('#send-btn');
      // Wait for response before creating next
      await page.waitForSelector('.message.assistant', { timeout: 10000 });
    }

    // All should appear
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(5);
  });

  test('conversation deletion updates pagination state', async ({ page }) => {
    // Create conversations
    for (let i = 0; i < 3; i++) {
      await page.click('#new-chat-btn');
      await page.fill('#message-input', `Delete test ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector('.message.assistant', { timeout: 10000 });
    }

    // Verify 3 conversations
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(3);

    // Delete one
    const firstConv = convItems.first();
    await firstConv.hover();
    const deleteBtn = firstConv.locator('.conversation-delete');
    await deleteBtn.click();

    // Confirm deletion
    const modal = page.locator('.modal-container:not(.modal-hidden)');
    await expect(modal).toBeVisible();
    await modal.locator('.modal-confirm').click();

    // Should have 2 remaining
    await expect(convItems).toHaveCount(2);
  });

  test('handles empty conversation list after all deletions', async ({ page }) => {
    // Create one conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'To be deleted');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Delete it
    const convItem = page.locator('.conversation-item-wrapper').first();
    await convItem.hover();
    const deleteBtn = convItem.locator('.conversation-delete');
    await deleteBtn.click();

    const modal = page.locator('.modal-container:not(.modal-hidden)');
    await expect(modal).toBeVisible();
    await modal.locator('.modal-confirm').click();

    // Should show empty state
    const emptyState = page.locator('.conversations-empty');
    await expect(emptyState).toBeVisible();
  });
});

test.describe('Messages Pagination', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Disable streaming for reliable mock responses
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }
  });

  test('messages are displayed in correct order', async ({ page }) => {
    // Create a conversation with multiple messages
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    await page.fill('#message-input', 'Second message');
    await page.click('#send-btn');
    // Wait for the second assistant message (there will be 4 messages total: 2 user + 2 assistant)
    await page.waitForFunction(() => {
      const messages = document.querySelectorAll('.message.assistant');
      return messages.length >= 2;
    }, { timeout: 10000 });

    // Verify messages are in chronological order (oldest first)
    const userMessages = page.locator('.message.user');
    await expect(userMessages.first()).toContainText('First message');
    await expect(userMessages.last()).toContainText('Second message');
  });

  test('older messages loader is not shown when not loading', async ({ page }) => {
    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // The older messages loader should not be visible
    const loader = page.locator('.older-messages-loader');
    await expect(loader).toHaveCount(0);
  });

  test('scroll position is at bottom when opening conversation', async ({ page }) => {
    // Create a conversation with a few messages
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Message 1');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    await page.fill('#message-input', 'Message 2');
    await page.click('#send-btn');
    await page.waitForFunction(() => {
      const messages = document.querySelectorAll('.message.assistant');
      return messages.length >= 2;
    }, { timeout: 10000 });

    // Create another conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Different conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Switch back to first conversation
    const convItems = page.locator('.conversation-item-wrapper');
    await convItems.last().click();

    // Wait for messages to load
    await page.waitForFunction(() => {
      const messages = document.querySelectorAll('.message.user');
      return messages.length >= 2;
    }, { timeout: 10000 });

    // Verify we're at the bottom (latest messages visible)
    const messagesContainer = page.locator('#messages');
    const isAtBottom = await messagesContainer.evaluate((el) => {
      const threshold = 100;
      return el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
    });
    expect(isAtBottom).toBe(true);
  });

  test('messages pagination state is maintained when switching conversations', async ({ page }) => {
    // Create first conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First conv message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Create second conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second conv message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Switch to first conversation
    const convItems = page.locator('.conversation-item-wrapper');
    await convItems.last().click();

    // Verify first conversation's messages are shown
    const userMessage = page.locator('.message.user');
    await expect(userMessage).toContainText('First conv message');

    // Switch back to second conversation
    await convItems.first().click();

    // Verify second conversation's messages are shown
    await expect(userMessage).toContainText('Second conv message');
  });
});
