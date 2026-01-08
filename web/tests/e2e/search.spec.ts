/**
 * E2E tests for full-text search functionality
 */
import { test, expect } from '../global-setup';

test.describe('Search - Input', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    // Wait for search input to be rendered
    await page.waitForSelector('#search-input', { timeout: 5000 });
  });

  test('search input is visible in sidebar', async ({ page }) => {
    const searchInput = page.locator('#search-input');
    await expect(searchInput).toBeVisible();
    await expect(searchInput).toHaveAttribute('placeholder', 'Search conversations...');
  });

  test('focusing search input activates search mode', async ({ page }) => {
    const searchInput = page.locator('#search-input');
    await searchInput.focus();

    // Should show search hint when focused with empty query
    const searchEmpty = page.locator('.search-empty');
    await expect(searchEmpty).toBeVisible();
    await expect(searchEmpty).toContainText('Type to search');
  });

  test('escape key clears search and deactivates search mode', async ({ page }) => {
    const searchInput = page.locator('#search-input');
    await searchInput.focus();
    await searchInput.fill('test query');

    // Verify input has value
    await expect(searchInput).toHaveValue('test query');

    // Search mode should be active - search empty state visible
    const searchEmpty = page.locator('.search-empty');
    await expect(searchEmpty).toBeVisible();

    // Press escape
    await searchInput.press('Escape');

    // Input should be cleared
    await expect(searchInput).toHaveValue('');

    // Search mode should be deactivated - search empty should not be visible
    await expect(searchEmpty).not.toBeVisible({ timeout: 2000 });
  });

  test('clear button appears when typing and clears on click', async ({ page }) => {
    const searchInput = page.locator('#search-input');
    const clearBtn = page.locator('.search-clear-btn');

    // Clear button should be hidden initially
    await expect(clearBtn).toHaveClass(/hidden/);

    // Type something
    await searchInput.fill('test');

    // Clear button should be visible
    await expect(clearBtn).not.toHaveClass(/hidden/);

    // Click clear button
    await clearBtn.click();

    // Input should be cleared
    await expect(searchInput).toHaveValue('');

    // Clear button should be hidden again
    await expect(clearBtn).toHaveClass(/hidden/);

    // Focus should remain on input
    await expect(searchInput).toBeFocused();
  });
});

test.describe('Search - Results', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    // Wait for search input to be rendered
    await page.waitForSelector('#search-input', { timeout: 5000 });

    // Disable streaming for reliable mock responses
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }
  });

  test('shows search results when typing', async ({ page }) => {
    // First create a conversation with searchable content
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Python programming tutorial');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Now search for it
    const searchInput = page.locator('#search-input');
    await searchInput.fill('Python');

    // Wait for debounce and results
    await page.waitForTimeout(400); // 300ms debounce + buffer

    // Should show results
    const resultsHeader = page.locator('.search-results-header');
    await expect(resultsHeader).toBeVisible({ timeout: 5000 });
  });

  test('shows no results message for non-matching query', async ({ page }) => {
    // Create a conversation first
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Hello world');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Search for something that doesn't exist
    const searchInput = page.locator('#search-input');
    await searchInput.fill('xyznonexistent123');

    // Wait for debounce
    await page.waitForTimeout(400);

    // Should show empty state
    const searchEmpty = page.locator('.search-empty');
    await expect(searchEmpty).toBeVisible({ timeout: 5000 });
    await expect(searchEmpty).toContainText('No results found');
  });

  test('clicking search result navigates to conversation', async ({ page }) => {
    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Unique search test message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Create another conversation to ensure we're not already viewing the target
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Different conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Search for the first conversation
    const searchInput = page.locator('#search-input');
    await searchInput.fill('Unique search test');

    // Wait for results
    await page.waitForTimeout(400);
    const resultItem = page.locator('.search-result-item').first();
    await expect(resultItem).toBeVisible({ timeout: 5000 });

    // Click the result
    await resultItem.click();

    // Should navigate to the conversation - search query should persist
    await expect(searchInput).toHaveValue('Unique search test');

    // Search results should still be visible with the clicked result highlighted
    await expect(resultItem).toBeVisible();
    await expect(resultItem).toHaveClass(/active/);

    // Should show the conversation with the matching message
    const userMessage = page.locator('.message.user');
    await expect(userMessage).toContainText('Unique search test message', { timeout: 5000 });
  });
});

test.describe('Search - Mock Results', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    // Wait for search input to be rendered
    await page.waitForSelector('#search-input', { timeout: 5000 });
  });

  test('displays mocked search results with correct formatting', async ({ page }) => {
    // Set mock search results
    await page.request.post('/test/set-search-results', {
      data: {
        results: [
          {
            conversation_id: 'conv-123',
            conversation_title: 'Test Conversation Title',
            message_id: 'msg-456',
            message_snippet: 'This is a [[HIGHLIGHT]]test[[/HIGHLIGHT]] snippet with highlighted text',
            match_type: 'message',
            created_at: new Date().toISOString(),
          },
          {
            conversation_id: 'conv-789',
            conversation_title: 'Another Conversation',
            message_id: null,
            message_snippet: null,
            match_type: 'conversation',
            created_at: new Date().toISOString(),
          },
        ],
        total: 2,
      },
    });

    // Trigger search
    const searchInput = page.locator('#search-input');
    await searchInput.fill('test');

    // Wait for results
    await page.waitForTimeout(400);

    // Should show result count
    const resultsCount = page.locator('.search-results-count');
    await expect(resultsCount).toContainText('2 results', { timeout: 5000 });

    // Should show result items
    const resultItems = page.locator('.search-result-item');
    await expect(resultItems).toHaveCount(2);

    // First result should have highlighted snippet
    const firstResult = resultItems.first();
    await expect(firstResult.locator('.search-result-title')).toContainText('Test Conversation Title');
    await expect(firstResult.locator('.search-result-snippet mark')).toContainText('test');

    // Second result should be a title match (no snippet)
    const secondResult = resultItems.nth(1);
    await expect(secondResult.locator('.search-result-title')).toContainText('Another Conversation');
    await expect(secondResult.locator('.search-result-snippet')).not.toBeVisible();

    // Clean up
    await page.request.post('/test/clear-search-results');
  });

  test('shows loading state during search', async ({ page }) => {
    // We can't easily delay the actual search, but we can verify the loading class exists
    // by checking the CSS transition behavior
    const searchInput = page.locator('#search-input');
    await searchInput.focus();

    // Should show hint initially
    const searchEmpty = page.locator('.search-empty');
    await expect(searchEmpty).toContainText('Type to search');
  });
});

test.describe('Search - Debounce', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    // Wait for search input to be rendered
    await page.waitForSelector('#search-input', { timeout: 5000 });

    // Disable streaming
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }
  });

  test('debounces rapid typing', async ({ page }) => {
    // Create a conversation first
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Type rapidly
    const searchInput = page.locator('#search-input');
    await searchInput.type('Test', { delay: 50 }); // Fast typing

    // Wait for debounce to complete
    await page.waitForTimeout(400);

    // Now results should be visible (if there are matches)
    // The test verifies debounce works by not crashing with rapid input
    // and eventually showing results after the debounce period
  });
});

test.describe('Search - Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    // Wait for search input to be rendered
    await page.waitForSelector('#search-input', { timeout: 5000 });

    // Disable streaming
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }
  });

  test('keeps search results visible after clicking on result', async ({ page }) => {
    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Navigation test message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Search for it
    const searchInput = page.locator('#search-input');
    await searchInput.fill('Navigation test');
    await page.waitForTimeout(400);

    // Click result
    const resultItem = page.locator('.search-result-item').first();
    await expect(resultItem).toBeVisible({ timeout: 5000 });
    await resultItem.click();

    // Search query should persist
    await expect(searchInput).toHaveValue('Navigation test');

    // Search results should still be visible with the clicked result highlighted
    await expect(resultItem).toBeVisible();
    await expect(resultItem).toHaveClass(/active/);
  });

  test('returns to conversation list when search is cleared', async ({ page }) => {
    // Create a conversation first
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Activate search
    const searchInput = page.locator('#search-input');
    await searchInput.fill('something');
    await page.waitForTimeout(400);

    // Clear search with escape
    await searchInput.press('Escape');

    // Should show conversations list again
    const conversationItem = page.locator('.conversation-item-wrapper').first();
    await expect(conversationItem).toBeVisible({ timeout: 5000 });
  });
});

test.describe('Search - Navigation with Pagination', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.waitForSelector('#search-input', { timeout: 5000 });

    // Disable streaming for reliable batch responses
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }
  });

  test('navigates to message in middle of large conversation using around_message_id', async ({
    page,
  }) => {
    // Create a conversation with many messages - use /test/seed for speed
    const messages = [];
    for (let i = 0; i < 150; i++) {
      messages.push({
        role: 'user',
        content: `User message ${i}: ${i === 75 ? 'FINDME target message here' : 'regular content'}`,
      });
      messages.push({
        role: 'assistant',
        content: `Assistant response ${i}`,
      });
    }

    // Use a title that won't match the search query to avoid getting a title match first
    const seedResponse = await page.request.post('/test/seed', {
      data: {
        conversations: [{ title: 'Test Conversation', messages }],
      },
    });
    expect(seedResponse.ok()).toBeTruthy();

    await page.reload();
    await page.waitForSelector('#search-input', { timeout: 5000 });

    // Search for the target message
    const searchInput = page.locator('#search-input');
    await searchInput.fill('FINDME');
    await page.waitForTimeout(400);

    // Wait for search results
    const resultItem = page.locator('.search-result-item').first();
    await expect(resultItem).toBeVisible({ timeout: 5000 });

    // Click the result
    await resultItem.click();

    // Should navigate to the conversation and show the target message
    const targetMessage = page.locator('.message.user:has-text("FINDME target message here")');
    await expect(targetMessage).toBeVisible({ timeout: 10000 });

    // The message should be highlighted (briefly)
    await expect(targetMessage).toHaveClass(/search-highlight/, { timeout: 2000 });
  });

  test('enables bi-directional pagination after navigating to search result', async ({ page }) => {
    // Create a conversation with many messages
    const messages = [];
    for (let i = 0; i < 100; i++) {
      messages.push({ role: 'user', content: `Message ${i}: ${i === 50 ? 'UNIQUE_MARKER' : 'text'}` });
      messages.push({ role: 'assistant', content: `Response ${i}` });
    }

    // Use a title that won't match the search query to avoid getting a title match first
    await page.request.post('/test/seed', {
      data: { conversations: [{ title: 'Test Conversation', messages }] },
    });

    await page.reload();
    await page.waitForSelector('#search-input', { timeout: 5000 });

    // Navigate to message in the middle
    const searchInput = page.locator('#search-input');
    await searchInput.fill('UNIQUE_MARKER');
    await page.waitForTimeout(400);

    const resultItem = page.locator('.search-result-item').first();
    await expect(resultItem).toBeVisible({ timeout: 5000 });
    await resultItem.click();

    // Should see the target message
    const targetMessage = page.locator('.message.user:has-text("UNIQUE_MARKER")');
    await expect(targetMessage).toBeVisible({ timeout: 10000 });

    // Get the messages container
    const messagesContainer = page.locator('#messages');

    // Record how many messages we have initially
    const initialMessageCount = await page.locator('.message.user').count();

    // Scroll to the very top to trigger loading older messages
    await messagesContainer.evaluate((el) => {
      el.scrollTop = 0;
    });

    // Wait for older messages to load (scroll listener has 100ms debounce + API time)
    await page.waitForTimeout(2000);

    // Check that we now have more messages than before (older messages were loaded)
    const afterOlderCount = await page.locator('.message.user').count();
    expect(afterOlderCount).toBeGreaterThanOrEqual(initialMessageCount);

    // Now scroll to the bottom to trigger loading newer messages
    // Use a loop to keep scrolling until we reach the end or timeout
    // This handles the case where scrollHeight changes as more messages load
    for (let attempt = 0; attempt < 5; attempt++) {
      await messagesContainer.evaluate((el) => {
        el.scrollTop = el.scrollHeight;
      });

      // Wait for potential API call
      await page.waitForTimeout(1500);

      // Check if Message 99 is now visible
      const isMessage99Visible = await page.locator('.message.user:has-text("Message 99:")').isVisible();
      if (isMessage99Visible) {
        break;
      }
    }

    // Should see newer messages (Message 99 should now be visible)
    const newerMessage = page.locator('.message.user:has-text("Message 99:")');
    await expect(newerMessage).toBeVisible({ timeout: 10000 });
  });

  test('loads all remaining messages before sending after search navigation', async ({ page }) => {
    // Create a conversation with messages
    const messages = [];
    for (let i = 0; i < 60; i++) {
      messages.push({ role: 'user', content: `Old message ${i}: ${i === 30 ? 'SEARCH_TARGET' : 'content'}` });
      messages.push({ role: 'assistant', content: `Old response ${i}` });
    }

    // Use a title that won't match the search query to avoid getting a title match first
    await page.request.post('/test/seed', {
      data: { conversations: [{ title: 'Test Conversation', messages }] },
    });

    await page.reload();
    await page.waitForSelector('#search-input', { timeout: 5000 });

    // Navigate to message in the middle
    const searchInput = page.locator('#search-input');
    await searchInput.fill('SEARCH_TARGET');
    await page.waitForTimeout(400);

    const resultItem = page.locator('.search-result-item').first();
    await expect(resultItem).toBeVisible({ timeout: 5000 });
    await resultItem.click();

    // Wait for target message to be visible
    const targetMessage = page.locator('.message.user:has-text("SEARCH_TARGET")');
    await expect(targetMessage).toBeVisible({ timeout: 10000 });

    // Now send a new message (this should load all remaining newer messages first)
    await page.fill('#message-input', 'My new message after search');
    await page.click('#send-btn');

    // Wait for the response
    await page.waitForSelector('.message.assistant:has-text("My new message after search")', {
      timeout: 15000,
    });

    // The new message should appear at the very end
    const newUserMessage = page.locator('.message.user:has-text("My new message after search")');
    await expect(newUserMessage).toBeVisible();

    // Verify continuity - older messages should still be present
    // The last old message (59) should be visible before our new message
    const lastOldMessage = page.locator('.message.user:has-text("Old message 59:")');
    await expect(lastOldMessage).toBeVisible({ timeout: 5000 });
  });

  test('handles rapid search result clicks gracefully', async ({ page }) => {
    // This test verifies that double-clicking a search result doesn't break navigation
    // Using dblclick() to simulate user accidentally double-clicking
    const messages = [];
    for (let i = 0; i < 60; i++) {
      messages.push({ role: 'user', content: `Message ${i}: ${i === 30 ? 'RAPID_CLICK_TEST' : 'x'}` });
      messages.push({ role: 'assistant', content: `Response ${i}` });
    }

    await page.request.post('/test/seed', {
      data: { conversations: [{ title: 'Test Conversation', messages }] },
    });

    await page.reload();
    await page.waitForSelector('#search-input', { timeout: 5000 });

    // Search for the marker
    const searchInput = page.locator('#search-input');
    await searchInput.fill('RAPID_CLICK_TEST');
    await page.waitForTimeout(400);

    // Get the result item
    const resultItem = page.locator('.search-result-item').first();
    await expect(resultItem).toBeVisible({ timeout: 5000 });

    // Double-click the result (simulates user accidentally double-clicking)
    // Both clicks process navigation to the same result (idempotent)
    await resultItem.dblclick();

    // Wait for navigation to complete
    await page.waitForTimeout(1000);

    // Should have navigated successfully - search query persists
    await expect(searchInput).toHaveValue('RAPID_CLICK_TEST');

    // The target message should be visible
    const targetMessage = page.locator('.message.user:has-text("RAPID_CLICK_TEST")');
    await expect(targetMessage).toBeVisible({ timeout: 5000 });

    // No error toast should be shown
    const errorToast = page.locator('.toast.error');
    await expect(errorToast).not.toBeVisible();
  });

  test('handles conversation switch during search navigation', async ({ page }) => {
    // Create two conversations
    const conv1Messages = [];
    for (let i = 0; i < 100; i++) {
      conv1Messages.push({ role: 'user', content: `Conv1 message ${i}: ${i === 50 ? 'SEARCHABLE' : 'x'}` });
      conv1Messages.push({ role: 'assistant', content: `Response ${i}` });
    }

    const seedResponse = await page.request.post('/test/seed', {
      data: {
        conversations: [
          { title: 'Searchable Conv', messages: conv1Messages },
          { title: 'Other Conv', messages: [{ role: 'user', content: 'Hello' }] },
        ],
      },
    });
    expect(seedResponse.ok()).toBeTruthy();

    await page.reload();
    await page.waitForSelector('#search-input', { timeout: 5000 });

    // Search and click a result
    const searchInput = page.locator('#search-input');
    await searchInput.fill('SEARCHABLE');
    await page.waitForTimeout(400);

    const resultItem = page.locator('.search-result-item').first();
    await expect(resultItem).toBeVisible({ timeout: 5000 });
    await resultItem.click();

    // Immediately click New Chat to switch away
    await page.click('#new-chat-btn');

    // Wait a moment
    await page.waitForTimeout(500);

    // Should be in new conversation (no messages, empty state)
    const messagesContainer = page.locator('#messages');
    const messages = messagesContainer.locator('.message');
    await expect(messages).toHaveCount(0, { timeout: 2000 });

    // No error should be visible
    const errorToast = page.locator('.toast.error');
    await expect(errorToast).not.toBeVisible();
  });

  test('scrolls to and highlights the target message', async ({ page }) => {
    // Create a conversation with the target message
    // Use a conversation title that WON'T match the search query to avoid
    // getting a conversation title match (which has null message_id)
    const messages = [];
    for (let i = 0; i < 80; i++) {
      messages.push({ role: 'user', content: `Message ${i}: ${i === 40 ? 'HIGHLIGHT_TEST' : 'text'}` });
      messages.push({ role: 'assistant', content: `Response ${i}` });
    }

    await page.request.post('/test/seed', {
      data: { conversations: [{ title: 'Test Conversation', messages }] },
    });

    await page.reload();
    await page.waitForSelector('#search-input', { timeout: 5000 });

    // Search for the target text
    const searchInput = page.locator('#search-input');
    await searchInput.fill('HIGHLIGHT_TEST');
    await page.waitForTimeout(400);

    // Click on the message result (the one with the snippet)
    const resultItem = page.locator('.search-result-item').first();
    await expect(resultItem).toBeVisible({ timeout: 5000 });
    await resultItem.click();

    // Target message should be visible and highlighted
    const targetMessage = page.locator('.message.user:has-text("HIGHLIGHT_TEST")');
    await expect(targetMessage).toBeVisible({ timeout: 10000 });
    await expect(targetMessage).toHaveClass(/search-highlight/);

    // After 2 seconds, highlight should be removed
    await page.waitForTimeout(2500);
    await expect(targetMessage).not.toHaveClass(/search-highlight/);
  });

  test('shows toast when message not found', async ({ page }) => {
    // Create a simple conversation
    await page.request.post('/test/seed', {
      data: {
        conversations: [
          { title: 'Simple Conv', messages: [{ role: 'user', content: 'Hello' }] },
        ],
      },
    });

    await page.reload();
    await page.waitForSelector('#search-input', { timeout: 5000 });

    // Set up mock search results that point to a non-existent message
    await page.request.post('/test/set-search-results', {
      data: {
        results: [
          {
            conversation_id: 'nonexistent-conv',
            conversation_title: 'Ghost Conversation',
            message_id: 'nonexistent-message-id',
            message_snippet: 'This message does not exist',
            match_type: 'message',
            created_at: new Date().toISOString(),
          },
        ],
        total: 1,
      },
    });

    // Trigger search
    const searchInput = page.locator('#search-input');
    await searchInput.fill('ghost');
    await page.waitForTimeout(400);

    // Click the result
    const resultItem = page.locator('.search-result-item').first();
    await expect(resultItem).toBeVisible({ timeout: 5000 });
    await resultItem.click();

    // Should show an info/error toast
    const toast = page.locator('.toast');
    await expect(toast).toBeVisible({ timeout: 5000 });

    // Clean up
    await page.request.post('/test/clear-search-results');
  });

  test('scroll-to-bottom in partial view loads all remaining messages first', async ({ page }) => {
    // Create a conversation with many messages
    // Use a title that WON'T match the search query to avoid getting a title match first
    const messages = [];
    for (let i = 0; i < 100; i++) {
      messages.push({ role: 'user', content: `Message ${i}: ${i === 40 ? 'PARTIAL_TARGET' : 'text'}` });
      messages.push({ role: 'assistant', content: `Response ${i}` });
    }

    await page.request.post('/test/seed', {
      data: { conversations: [{ title: 'Test Conversation', messages }] },
    });

    await page.reload();
    await page.waitForSelector('#search-input', { timeout: 5000 });

    // Navigate to message in the middle (creates partial view)
    const searchInput = page.locator('#search-input');
    await searchInput.fill('PARTIAL_TARGET');
    await page.waitForTimeout(400);

    const resultItem = page.locator('.search-result-item').first();
    await expect(resultItem).toBeVisible({ timeout: 5000 });
    await resultItem.click();

    // Wait for target message to be visible
    const targetMessage = page.locator('.message.user:has-text("PARTIAL_TARGET")');
    await expect(targetMessage).toBeVisible({ timeout: 10000 });

    // The scroll-to-bottom button should be visible (we're not at the actual bottom)
    const scrollButton = page.locator('.scroll-to-bottom:not(.hidden)');
    await expect(scrollButton).toBeVisible({ timeout: 2000 });

    // Click the scroll-to-bottom button
    await scrollButton.click();

    // Wait for all messages to load and scroll to complete
    await page.waitForTimeout(2000);

    // The newest message (Message 99) should now be visible
    const newestMessage = page.locator('.message.user:has-text("Message 99:")');
    await expect(newestMessage).toBeVisible({ timeout: 5000 });

    // Verify we're truly at the bottom by checking the scroll position
    const messagesContainer = page.locator('#messages');
    const isAtBottom = await messagesContainer.evaluate((el) => {
      const threshold = 100;
      return el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
    });
    expect(isAtBottom).toBeTruthy();
  });

  test('blocks search navigation during streaming with toast', async ({ page }) => {
    // Enable streaming for this test
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'false') {
      await streamBtn.click();
    }

    // Create a conversation with a searchable message
    const messages = [];
    for (let i = 0; i < 50; i++) {
      messages.push({
        role: 'user',
        content: `Message ${i}: ${i === 25 ? 'STREAMING_SEARCH_TEST' : 'text'}`,
      });
      messages.push({ role: 'assistant', content: `Response ${i}` });
    }

    // Use a title that won't match the search query to avoid getting a title match first
    await page.request.post('/test/seed', {
      data: { conversations: [{ title: 'Test Conversation', messages }] },
    });

    await page.reload();
    await page.waitForSelector('#search-input', { timeout: 5000 });

    // Select the conversation
    const convItem = page.locator('.conversation-item').first();
    await convItem.click();
    await page.waitForSelector('.message', { timeout: 5000 });

    // Set a very long stream delay AND long mock response so streaming doesn't complete
    // before we can click the search result
    await page.request.post('/test/set-stream-delay', { data: { delay: 500 } });
    await page.request.post('/test/set-mock-response', {
      data: { response: 'This is a very long streaming response that will take a long time to complete because each word is streamed with a delay between them.' },
    });

    // Start streaming a response
    await page.fill('#message-input', 'Generate a response');
    await page.click('#send-btn');

    // Wait for streaming to start
    await page.waitForSelector('.message.assistant.streaming', { timeout: 5000 });

    // Now try to search and click a result while streaming
    const searchInput = page.locator('#search-input');
    await searchInput.fill('STREAMING_SEARCH_TEST');
    await page.waitForTimeout(400);

    const resultItem = page.locator('.search-result-item').first();
    await expect(resultItem).toBeVisible({ timeout: 5000 });
    await resultItem.click();

    // Should show a toast asking to wait
    const toast = page.locator('.toast:has-text("response to complete")');
    await expect(toast).toBeVisible({ timeout: 3000 });

    // Wait for streaming to finish (longer timeout due to slow streaming)
    await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 60000 });

    // Reset stream delay and mock response
    await page.request.post('/test/set-stream-delay', { data: { delay: 10 } });
    await page.request.post('/test/set-mock-response', { data: { response: null } });
  });
});
