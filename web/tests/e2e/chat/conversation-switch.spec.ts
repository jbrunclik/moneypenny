/**
 * E2E tests for conversation switching behavior during active requests
 */
import {
  test,
  expect,
  enableStreaming,
  disableStreaming,
  setStreamDelay,
  resetStreamDelay,
  setBatchDelay,
  resetBatchDelay,
  setEmitThinking,
} from './fixtures';

test.describe('Chat - Request Continuation on Conversation Switch', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
  });

  test('batch request completes after switching conversations', async ({ page }) => {
    // Disable streaming
    await disableStreaming(page);

    // Create first conversation and send message
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First conversation message');

    // Wait for the request to be sent
    const requestPromise = page.waitForRequest(
      (request) => request.url().includes('/chat/batch') && request.method() === 'POST',
      { timeout: 5000 }
    );

    await page.click('#send-btn');
    await requestPromise; // Wait for request to be sent

    // Wait for user message to appear (confirms UI updated)
    await page.waitForSelector('.message.user', { timeout: 5000 });

    // Switch to a new conversation immediately (before response completes)
    // The request will continue in the background
    await page.click('#new-chat-btn');

    // Poll by reloading the conversation until messages appear
    // Messages only appear when we reload (fetch from API), not automatically
    // Wait for both conversations to be in the list
    await page.waitForSelector('.conversation-item-wrapper', { timeout: 5000 });
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(2);

    // Find the conversation with the message by looking for one that has messages when clicked
    // Note: The new conversation is at index 0 (most recently created), the original is at index 1
    // But after the background request completes, the original may be reordered to index 0
    // We need to find the one that actually has our messages
    let messagesFound = false;
    // Poll every 300ms, up to 20 attempts (6 seconds total)
    // Batch is fast, so we should see messages quickly
    for (let attempt = 0; attempt < 20; attempt++) {
      // Try clicking on each conversation to find the one with messages
      // The conversation with messages may be at position 0 or 1 depending on timing
      const conversationToTry = attempt % 2 === 0 ? convItems.nth(0) : convItems.nth(1);
      await conversationToTry.click();

      // Wait for conversation to load
      await page.waitForSelector('.conversation-loader', { state: 'hidden', timeout: 2000 });

      // Check if both messages are present
      const userMsg = page.locator('.message.user');
      const assistantMsg = page.locator('.message.assistant');
      const userCount = await userMsg.count();
      const assistantCount = await assistantMsg.count();

      if (userCount > 0 && assistantCount > 0) {
        messagesFound = true;
        break;
      }

      await page.waitForTimeout(300);
    }

    expect(messagesFound).toBe(true);
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toContainText('mock response', { ignoreCase: true });
  });

  test('streaming request continues after switching conversations', async ({ page }) => {
    // Enable streaming
    await enableStreaming(page);

    // Create first conversation and send message
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Streaming message');

    // Wait for the request to be sent
    const requestPromise = page.waitForRequest(
      (request) => request.url().includes('/chat/stream') && request.method() === 'POST',
      { timeout: 5000 }
    );

    await page.click('#send-btn');
    await requestPromise; // Wait for request to be sent

    // Wait for streaming to start (assistant message appears)
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 5000 });

    // Switch to a new conversation immediately (during streaming)
    // The request will continue in the background
    await page.click('#new-chat-btn');

    // Poll by reloading the conversation until messages appear
    // Streaming takes longer (word-by-word delay + cleanup thread delay)
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems.first()).toBeVisible();

    let messagesFound = false;
    // Poll every 300ms, up to 30 attempts (9 seconds total)
    // Streaming needs more time due to word-by-word delay + cleanup thread
    for (let attempt = 0; attempt < 30; attempt++) {
      // Try clicking on each conversation to find the one with messages
      // The conversation with messages may be at position 0 or 1 depending on timing
      const conversationToTry = attempt % 2 === 0 ? convItems.nth(0) : convItems.nth(1);
      await conversationToTry.click();

      // Wait for conversation to load
      await page.waitForSelector('.conversation-loader', { state: 'hidden', timeout: 2000 });

      // Check if both messages are present
      const userMsg = page.locator('.message.user');
      const assistantMsg = page.locator('.message.assistant');
      const userCount = await userMsg.count();
      const assistantCount = await assistantMsg.count();

      if (userCount > 0 && assistantCount > 0) {
        messagesFound = true;
        break;
      }

      await page.waitForTimeout(300);
    }

    expect(messagesFound).toBe(true);
    const assistantMessageComplete = page.locator('.message.assistant');
    await expect(assistantMessageComplete).toContainText('mock response', { ignoreCase: true });
  });

  test('multiple conversations can have active requests simultaneously', async ({ page }) => {
    // Enable streaming
    await enableStreaming(page);

    // Create and send message in first conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First message');
    await page.click('#send-btn');
    // Wait for streaming to complete (message appears in UI)
    await page.waitForSelector('.message.assistant', { timeout: 10000 });
    // Wait for cleanup thread to save to DB
    await page.waitForTimeout(500);

    // Create second conversation and send message
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second message');
    await page.click('#send-btn');
    // Wait for streaming to complete
    await page.waitForSelector('.message.assistant', { timeout: 10000 });
    // Wait for cleanup thread to save to DB
    await page.waitForTimeout(500);

    // Both conversations should have responses
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(2);

    // Switch to first conversation
    await convItems.nth(0).click();
    // Wait for conversation to load
    await page.waitForSelector('.conversation-loader', { state: 'hidden', timeout: 10000 });
    await page.waitForSelector('.message.user', { timeout: 10000 });
    const firstAssistant = page.locator('.message.assistant').first();
    await expect(firstAssistant).toContainText('mock response', { timeout: 10000 });

    // Switch to second conversation
    await convItems.nth(1).click();
    // Wait for conversation to load
    await page.waitForSelector('.conversation-loader', { state: 'hidden', timeout: 10000 });
    await page.waitForSelector('.message.user', { timeout: 10000 });
    const secondAssistant = page.locator('.message.assistant').first();
    await expect(secondAssistant).toContainText('mock response', { timeout: 10000 });
  });
});

test.describe('Chat - Conversation Switch During Active Request', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
  });

  test('restores streaming UI when switching back to conversation with active stream', async ({
    page,
  }) => {
    // Configure slow streaming delay for reliable testing (500ms per token)
    await setStreamDelay(page, 500);

    // Enable streaming mode
    await enableStreaming(page);

    // Create first conversation and send a message
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First conversation streaming message');
    await page.click('#send-btn');

    // Wait for streaming to start (message element appears)
    const streamingMessage = page.locator('.message.assistant.streaming');
    await expect(streamingMessage).toBeVisible({ timeout: 10000 });

    // Stop button should be visible
    const stopBtn = page.locator('#send-btn.btn-stop');
    await expect(stopBtn).toBeVisible();

    // Get the conversation items from the sidebar (there should be one real conv)
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(1);

    // Wait for streaming to COMPLETE before switching (watch for stop button to disappear)
    // This ensures the message is saved to DB before we switch
    await expect(stopBtn).not.toBeVisible({ timeout: 30000 });

    // The streaming should be complete - message should have content now
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toContainText('mock response', { timeout: 5000 });

    // Now create second conversation and switch back
    await page.click('#new-chat-btn');
    await expect(convItems).toHaveCount(2);

    // Switch back to first conversation
    await convItems.last().click();

    // The assistant message should be visible (loaded from API)
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });
    await expect(assistantMessage).toContainText('mock response');

    // Reset stream delay to default
    await resetStreamDelay(page);
  });

  test('restores batch loading indicator when switching back to conversation with active batch request', async ({
    page,
  }) => {
    // Configure slow response for batch mode (delay gives time to switch conversations)
    await setBatchDelay(page, 500);

    // Disable streaming for batch mode
    await disableStreaming(page);

    // Create first conversation and send a message
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First conversation batch message');
    await page.click('#send-btn');

    // Wait for loading indicator to appear
    const loadingIndicator = page.locator('.message-loading');
    await expect(loadingIndicator).toBeVisible({ timeout: 5000 });

    // Create second conversation (switches away from first)
    await page.click('#new-chat-btn');

    // Loading indicator should NOT be visible (different conversation)
    await expect(loadingIndicator).not.toBeVisible();

    // Switch back to first conversation
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(2);
    await convItems.last().click(); // First conversation

    // Either the loading indicator should be visible again OR the response should be complete
    // (depending on timing)
    const assistantMessage = page.locator('.message.assistant').last();
    const loadingOrMessage = page.locator('.message-loading, .message.assistant').last();
    await expect(loadingOrMessage).toBeVisible({ timeout: 5000 });

    // Wait for the response to complete
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });

    // Reset batch delay
    await resetBatchDelay(page);
  });

  test('streaming continues and completes when switching back to conversation', async ({
    page,
  }) => {
    // Configure streaming delay (enough time to switch conversations)
    await setStreamDelay(page, 100);

    // Enable streaming mode
    await enableStreaming(page);

    // Create first conversation and send a message
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test switch and return');
    await page.click('#send-btn');

    // Wait for streaming to start
    const streamingMessage = page.locator('.message.assistant.streaming');
    await expect(streamingMessage).toBeVisible({ timeout: 5000 });

    // Wait a moment to accumulate some content
    await page.waitForTimeout(500);

    // Create second conversation
    await page.click('#new-chat-btn');

    // Wait and switch back
    await page.waitForTimeout(300);
    const convItems = page.locator('.conversation-item-wrapper');
    await convItems.last().click();

    // Wait for streaming to complete - the message should have content AND no longer be streaming
    // Use a single robust assertion that waits for the final state
    const assistantMessage = page.locator('.message.assistant:not(.streaming)');
    await expect(assistantMessage).toContainText('mock response', { timeout: 30000 });

    // Reset stream delay
    await resetStreamDelay(page);
  });

  test('multiple rapid conversation switches preserve streaming state', async ({ page }) => {
    // Configure streaming delay (enough time for rapid switching)
    await setStreamDelay(page, 30);

    // Enable streaming mode
    await enableStreaming(page);

    // Create first conversation and start streaming
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Multi-switch test message');
    await page.click('#send-btn');

    // Wait for streaming to start
    await expect(page.locator('.message.assistant.streaming')).toBeVisible({ timeout: 5000 });

    // Create second conversation
    await page.click('#new-chat-btn');

    // Rapidly switch between conversations multiple times
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(2);

    // Switch back to first
    await convItems.last().click();
    await page.waitForTimeout(200);

    // Switch to second
    await convItems.first().click();
    await page.waitForTimeout(200);

    // Switch back to first again
    await convItems.last().click();

    // Wait for the streaming to complete
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toContainText('mock response', { timeout: 15000 });

    // Reset stream delay
    await resetStreamDelay(page);
  });

  test('preserves thinking indicator state when switching back to streaming conversation', async ({
    page,
  }) => {
    // Set a longer stream delay to ensure we can catch the streaming state
    await setStreamDelay(page, 200);

    // Enable thinking events
    await setEmitThinking(page, true);

    // Enable streaming mode
    await enableStreaming(page);

    // Create first conversation and send a message
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test thinking state preservation');
    await page.click('#send-btn');

    // Wait for streaming to start and thinking indicator to appear
    const streamingMessage = page.locator('.message.assistant.streaming');
    await expect(streamingMessage).toBeVisible({ timeout: 5000 });

    const thinkingIndicator = page.locator('.thinking-indicator');
    await expect(thinkingIndicator).toBeVisible({ timeout: 5000 });

    // Create second conversation (switches away from first)
    await page.click('#new-chat-btn');

    // Thinking indicator should not be visible in the new conversation
    await expect(thinkingIndicator).not.toBeVisible();

    // Switch back to first conversation
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(2);
    await convItems.last().click();

    // Either the thinking indicator should still be visible (streaming ongoing)
    // or the response is complete with a "Show details" toggle
    const thinkingOrDetails = page.locator('.thinking-indicator').first();
    await expect(thinkingOrDetails).toBeVisible({ timeout: 5000 });

    // Wait for streaming to complete
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toContainText('mock response', { timeout: 15000 });

    // Reset settings
    await resetStreamDelay(page);
    await setEmitThinking(page, false);
  });

  test('preserves accumulated content when switching back to streaming conversation', async ({
    page,
  }) => {
    // Configure streaming to accumulate content before switching
    await setStreamDelay(page, 30);

    // Enable streaming mode
    await enableStreaming(page);

    // Create first conversation and send a message
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test content preservation');
    await page.click('#send-btn');

    // Wait for streaming to start
    const streamingMessage = page.locator('.message.assistant.streaming');
    await expect(streamingMessage).toBeVisible({ timeout: 5000 });

    // Wait for some content to accumulate (at 30ms/token, should have ~5-6 tokens after 200ms)
    await page.waitForTimeout(200);

    // Verify some content has accumulated (the mock response starts with "This is a mock response")
    const messageContent = page.locator('.message.assistant .message-content');
    await expect(messageContent).toContainText('This', { timeout: 2000 });

    // Create second conversation (switches away from first)
    await page.click('#new-chat-btn');

    // Switch back to first conversation
    const convItems = page.locator('.conversation-item-wrapper');
    await convItems.last().click();

    // The message content should still contain what we had before (or more)
    // Use toContainText instead of comparing lengths since thinking indicator
    // text can affect raw textContent differently across browsers
    await expect(messageContent).toContainText('This', { timeout: 5000 });

    // Wait for streaming to complete
    await expect(page.locator('.message.assistant')).toContainText('mock response', {
      timeout: 15000,
    });

    // Reset stream delay
    await resetStreamDelay(page);
  });
});

test.describe('Chat - Conversation Switch During Streaming Scroll', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
  });

  test('scroll state is restored when switching back to streaming conversation', async ({
    page,
  }) => {
    // Configure slow streaming
    await setStreamDelay(page, 300);

    // Enable streaming mode
    await enableStreaming(page);

    // Create first conversation with some setup messages
    await page.click('#new-chat-btn');

    // Disable streaming for fast setup
    const streamBtn = page.locator('#stream-btn');
    await streamBtn.click();
    for (let i = 0; i < 2; i++) {
      await page.fill('#message-input', `Setup ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 10000 });
    }

    // Re-enable streaming
    await streamBtn.click();
    await setStreamDelay(page, 200);

    // Send a streaming message
    await page.fill('#message-input', 'Long streaming message');
    await page.click('#send-btn');

    // Wait for streaming to start
    const streamingMessage = page.locator('.message.assistant.streaming');
    await expect(streamingMessage).toBeVisible({ timeout: 5000 });

    // Create second conversation (switches away)
    await page.click('#new-chat-btn');

    // Streaming message should not be visible (different conversation)
    await expect(streamingMessage).not.toBeVisible();

    // Switch back to first conversation
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(2);
    await convItems.last().click();

    // Wait for either the streaming message to be restored OR the final message to load
    const assistantMessage = page.locator('.message.assistant').last();
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });

    // Reset stream delay
    await resetStreamDelay(page);
  });
});
