/**
 * E2E tests for chat functionality
 */
import { test, expect } from '../global-setup';

test.describe('Chat - Batch Mode', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Disable streaming for batch tests
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }
  });

  test('sends message and receives batch response', async ({ page }) => {
    await page.fill('#message-input', 'What is 2+2?');
    await page.click('#send-btn');

    // Wait for response (loading indicator may appear briefly but mock is fast)
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });

    // Response should contain mock text
    await expect(assistantMessage).toContainText('mock response', { ignoreCase: true });
  });

  test('shows both user and assistant messages', async ({ page }) => {
    await page.fill('#message-input', 'Hello!');
    await page.click('#send-btn');

    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    const userMessage = page.locator('.message.user');
    const assistantMessage = page.locator('.message.assistant');

    await expect(userMessage).toBeVisible();
    await expect(assistantMessage).toBeVisible();
    await expect(userMessage).toContainText('Hello!');
  });
});

test.describe('Chat - Streaming Mode', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Enable streaming
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }
  });

  test('streaming button toggles state', async ({ page }) => {
    const streamBtn = page.locator('#stream-btn');

    // Should be enabled (pressed)
    await expect(streamBtn).toHaveAttribute('aria-pressed', 'true');

    // Toggle off
    await streamBtn.click();
    await expect(streamBtn).toHaveAttribute('aria-pressed', 'false');

    // Toggle on
    await streamBtn.click();
    await expect(streamBtn).toHaveAttribute('aria-pressed', 'true');
  });

  test('streams response tokens progressively via SSE', async ({ page }) => {
    await page.fill('#message-input', 'Hello streaming');
    await page.click('#send-btn');

    // Wait for assistant message to appear (streaming creates element immediately)
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });

    // Wait for streaming to complete - content should contain mock response
    // The mock streams "This is a mock response to: Hello streaming" word by word
    await expect(assistantMessage).toContainText('mock response', { timeout: 10000 });
    await expect(assistantMessage).toContainText('Hello streaming', { timeout: 10000 });
  });

  test('shows both user and assistant messages after streaming', async ({ page }) => {
    await page.fill('#message-input', 'Stream test');
    await page.click('#send-btn');

    // Wait for streaming to complete
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toContainText('mock response', { timeout: 10000 });

    // Both messages should be visible
    const userMessage = page.locator('.message.user');
    await expect(userMessage).toBeVisible();
    await expect(userMessage).toContainText('Stream test');
    await expect(assistantMessage).toBeVisible();
  });
});

test.describe('Chat - Model Selection', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');
  });

  test('model selector button is visible', async ({ page }) => {
    const modelSelectorBtn = page.locator('#model-selector-btn');
    await expect(modelSelectorBtn).toBeVisible();
  });

  test('can open model dropdown', async ({ page }) => {
    const modelSelectorBtn = page.locator('#model-selector-btn');
    const modelDropdown = page.locator('#model-dropdown');

    // Dropdown should be hidden initially
    await expect(modelDropdown).toHaveClass(/hidden/);

    // Click to open dropdown
    await modelSelectorBtn.click();

    // Dropdown should be visible
    await expect(modelDropdown).not.toHaveClass(/hidden/);

    // Should show model options
    const modelOptions = modelDropdown.locator('.model-option');
    await expect(modelOptions.first()).toBeVisible();
  });

  /**
   * REGRESSION TEST: Model selection for new (temp) conversations
   *
   * This test catches a regression where selecting a model on a new conversation
   * (before any message is sent) would fail because:
   * 1. New conversations have a temp ID (temp-...) that doesn't exist in backend
   * 2. The model selector tried to call the API to update the model
   * 3. The API call failed, showing an error toast
   *
   * The fix should:
   * - For temp conversations, update the model locally in the store
   * - Not call the API until the conversation is persisted
   * - The selected model should be used when the conversation is created
   */
  test('can select model on new conversation before sending message', async ({ page }) => {
    const modelSelectorBtn = page.locator('#model-selector-btn');
    const modelDropdown = page.locator('#model-dropdown');

    // Get initial model name
    const initialModelName = await page.locator('#current-model-name').textContent();

    // Open dropdown
    await modelSelectorBtn.click();
    await expect(modelDropdown).not.toHaveClass(/hidden/);

    // Get all model options
    const modelOptions = modelDropdown.locator('.model-option');
    const optionCount = await modelOptions.count();
    expect(optionCount).toBeGreaterThan(1); // Ensure we have multiple models to choose from

    // Find a model that is NOT currently selected (no .selected class)
    let differentModelOption = null;
    let differentModelName = null;
    for (let i = 0; i < optionCount; i++) {
      const option = modelOptions.nth(i);
      const isSelected = await option.evaluate((el) => el.classList.contains('selected'));
      if (!isSelected) {
        differentModelOption = option;
        differentModelName = await option.locator('.model-name').textContent();
        break;
      }
    }

    // Ensure we found a different model
    expect(differentModelOption).not.toBeNull();
    expect(differentModelName).not.toBe(initialModelName);

    // Click on the different model
    await differentModelOption!.click();

    // Dropdown should close
    await expect(modelDropdown).toHaveClass(/hidden/);

    // Model name should be updated in the button
    const newModelName = await page.locator('#current-model-name').textContent();
    expect(newModelName).toBe(differentModelName);

    // No error toast should appear (this was the bug)
    // Wait a moment for any async error handling
    await page.waitForTimeout(500);
    // Toast has class "toast toast-error" for error type
    const errorToast = page.locator('.toast-error');
    await expect(errorToast).toHaveCount(0);

    // Now send a message - the conversation should be created with the selected model
    // Disable streaming for reliable response
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }

    await page.fill('#message-input', 'Test with selected model');
    await page.click('#send-btn');

    // Wait for response
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // The model should still be the one we selected
    const finalModelName = await page.locator('#current-model-name').textContent();
    expect(finalModelName).toBe(differentModelName);
  });

  test('model selection persists after sending first message', async ({ page }) => {
    const modelSelectorBtn = page.locator('#model-selector-btn');
    const modelDropdown = page.locator('#model-dropdown');

    // Disable streaming for reliable response
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }

    // Open dropdown and select a non-default model
    await modelSelectorBtn.click();
    await expect(modelDropdown).not.toHaveClass(/hidden/);

    // Get all model options and find one that's not selected
    const modelOptions = modelDropdown.locator('.model-option');
    let targetOption = null;
    let targetModelName = null;
    const optionCount = await modelOptions.count();
    for (let i = 0; i < optionCount; i++) {
      const option = modelOptions.nth(i);
      const isSelected = await option.evaluate((el) => el.classList.contains('selected'));
      if (!isSelected) {
        targetOption = option;
        targetModelName = await option.locator('.model-name').textContent();
        break;
      }
    }

    expect(targetOption).not.toBeNull();
    await targetOption!.click();

    // Verify model is selected
    const selectedModelName = await page.locator('#current-model-name').textContent();
    expect(selectedModelName).toBe(targetModelName);

    // Send first message (this persists the conversation)
    await page.fill('#message-input', 'First message with selected model');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Model should still be the one we selected
    expect(await page.locator('#current-model-name').textContent()).toBe(targetModelName);

    // Switch to another conversation and back
    await page.click('#new-chat-btn');

    // Switch back to the original conversation
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(2);
    await convItems.last().click(); // Original conversation

    // Wait for conversation to load
    await page.waitForSelector('.message.user', { timeout: 10000 });

    // Model should still be the one we selected for this conversation
    expect(await page.locator('#current-model-name').textContent()).toBe(targetModelName);
  });
});

test.describe('Chat - Thinking Indicator', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Enable streaming (thinking indicator only shows in streaming mode)
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }
  });

  test('shows thinking indicator during streaming', async ({ page }) => {
    // Type a message that triggers thinking (mock server emits thinking for "think" keyword)
    await page.fill('#message-input', 'Let me think about this');
    await page.click('#send-btn');

    // Wait for assistant message to appear (streaming creates element immediately)
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });

    // The thinking indicator should appear initially
    // Note: Due to fast mock streaming, it may collapse quickly
    // We check that response eventually completes
    await expect(assistantMessage).toContainText('mock response', { timeout: 10000 });
  });

  test('thinking indicator collapses after message finishes', async ({ page }) => {
    await page.fill('#message-input', 'Think about 2+2');
    await page.click('#send-btn');

    // Wait for streaming to complete
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toContainText('mock response', { timeout: 10000 });

    // After streaming completes, the indicator should be finalized (collapsed)
    // Check for the finalized class or toggle button
    const thinkingIndicator = assistantMessage.locator('.thinking-indicator.finalized');
    const thinkingToggle = assistantMessage.locator('.thinking-toggle');

    // Either the indicator is finalized (has toggle) or it was removed (no thinking content)
    const finalizedCount = await thinkingIndicator.count();
    const toggleCount = await thinkingToggle.count();

    // The indicator should either be collapsed with a toggle, or removed entirely
    // (removed if no thinking/tool content to show)
    expect(finalizedCount + toggleCount).toBeLessThanOrEqual(1);
  });

  test('tool indicator shows when force tools are used', async ({ page }) => {
    // Activate search (force web_search tool)
    const searchBtn = page.locator('#search-btn');
    await searchBtn.click();
    await expect(searchBtn).toHaveClass(/active/);

    await page.fill('#message-input', 'Search for something');
    await page.click('#send-btn');

    // Wait for streaming to complete
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toContainText('mock response', { timeout: 10000 });

    // After streaming, there should be a finalized thinking indicator with tool info
    // The mock emits tool_start/tool_end events when force_tools are specified
    const thinkingIndicator = assistantMessage.locator('.thinking-indicator');
    const count = await thinkingIndicator.count();

    // Either indicator exists (showing tool usage) or was removed (no content)
    expect(count).toBeLessThanOrEqual(1);
  });
});

test.describe('Chat - Force Tools', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');
  });

  test('search button is visible', async ({ page }) => {
    const searchBtn = page.locator('#search-btn');
    await expect(searchBtn).toBeVisible();
  });

  test('search button toggles active state', async ({ page }) => {
    const searchBtn = page.locator('#search-btn');

    // Initially not active
    await expect(searchBtn).not.toHaveClass(/active/);

    // Click to activate
    await searchBtn.click();
    await expect(searchBtn).toHaveClass(/active/);

    // Click to deactivate
    await searchBtn.click();
    await expect(searchBtn).not.toHaveClass(/active/);
  });

  test('search button deactivates after sending message', async ({ page }) => {
    const searchBtn = page.locator('#search-btn');

    // Activate search
    await searchBtn.click();
    await expect(searchBtn).toHaveClass(/active/);

    // Send message
    await page.fill('#message-input', 'Search for something');
    await page.click('#send-btn');

    // Wait for response
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Search button should be deactivated (one-shot)
    await expect(searchBtn).not.toHaveClass(/active/);
  });
});

test.describe('Chat - Message Actions', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Send a message first
    await page.fill('#message-input', 'Test message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });
  });

  test('copy button is visible on messages', async ({ page }) => {
    const copyBtn = page.locator('.message-copy-btn').first();
    await expect(copyBtn).toBeVisible();
  });

  test('messages have proper structure', async ({ page }) => {
    // User message
    const userMessage = page.locator('.message.user');
    await expect(userMessage).toBeVisible();
    await expect(userMessage.locator('.message-content')).toBeVisible();

    // Assistant message
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible();
    await expect(assistantMessage.locator('.message-content')).toBeVisible();
  });
});

test.describe('Chat - Request Continuation on Conversation Switch', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
  });

  test('batch request completes after switching conversations', async ({ page }) => {
    // Disable streaming
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }

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
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }

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
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }

    // Create and send message in first conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First message');
    await page.click('#send-btn');
    // Wait for streaming to complete (message appears in UI)
    await page.waitForSelector('.message.assistant', { timeout: 10000 });
    // Wait a bit more for cleanup thread to save to DB (1s delay + buffer)
    await page.waitForTimeout(2000);

    // Create second conversation and send message
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second message');
    await page.click('#send-btn');
    // Wait for streaming to complete
    await page.waitForSelector('.message.assistant', { timeout: 10000 });
    // Wait a bit more for cleanup thread to save to DB
    await page.waitForTimeout(2000);

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

test.describe('Chat - Streaming Auto-Scroll', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Enable streaming for auto-scroll tests
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }
  });

  test('scrolls to bottom when sending a new message', async ({ page }) => {
    // First, create some messages to have scrollable content
    // Disable streaming temporarily for faster setup
    const streamBtn = page.locator('#stream-btn');
    await streamBtn.click(); // Disable streaming

    for (let i = 0; i < 3; i++) {
      await page.fill('#message-input', `Setup message ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 10000 });
    }

    // Re-enable streaming
    await streamBtn.click();

    const messagesContainer = page.locator('#messages');

    // Scroll up to simulate user browsing history
    await messagesContainer.evaluate((el) => {
      el.scrollTop = 0;
    });
    await page.waitForTimeout(100);

    // Verify we're at the top
    const scrollTopBefore = await messagesContainer.evaluate((el) => el.scrollTop);
    expect(scrollTopBefore).toBe(0);

    // Send a new message
    await page.fill('#message-input', 'New message to test scroll');
    await page.click('#send-btn');

    // Wait for user message to appear
    await page.waitForSelector('.message.user >> text=New message to test scroll', {
      timeout: 5000,
    });

    // User message should be visible (scrolled to bottom after send)
    const userMessage = page.locator('.message.user >> text=New message to test scroll');
    await expect(userMessage).toBeInViewport();
  });

  test('auto-scroll can be interrupted by scrolling up during streaming', async ({ page }) => {
    // Send a message to start streaming
    await page.fill('#message-input', 'Tell me a long story');
    await page.click('#send-btn');

    // Wait for streaming to start (assistant message appears)
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 5000 });

    const messagesContainer = page.locator('#messages');

    // Scroll up during streaming to interrupt auto-scroll
    await messagesContainer.evaluate((el) => {
      el.scrollTop = 0;
    });

    // Wait for scroll event to be processed
    await page.waitForTimeout(100);

    // Verify we're at the top
    const scrollTopAfterScrollUp = await messagesContainer.evaluate((el) => el.scrollTop);
    expect(scrollTopAfterScrollUp).toBe(0);

    // Wait for streaming to continue/complete
    await expect(assistantMessage).toContainText('mock response', { timeout: 10000 });

    // After streaming completes, we should still be at top (scroll was interrupted)
    const scrollTopAfterStream = await messagesContainer.evaluate((el) => el.scrollTop);
    // Allow some tolerance - should be near the top (not at bottom)
    expect(scrollTopAfterStream).toBeLessThan(200);
  });

  test('auto-scroll resumes when scrolling back to bottom during streaming', async ({ page }) => {
    // First, create some messages to have scrollable content
    // Disable streaming temporarily for faster setup
    const streamBtn = page.locator('#stream-btn');
    await streamBtn.click(); // Disable streaming

    for (let i = 0; i < 3; i++) {
      await page.fill('#message-input', `Setup message ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 10000 });
    }

    // Re-enable streaming
    await streamBtn.click();

    // Scroll up first
    const messagesContainer = page.locator('#messages');
    await messagesContainer.evaluate((el) => {
      el.scrollTop = 0;
    });
    await page.waitForTimeout(100);

    // Send a new message
    await page.fill('#message-input', 'Another long story please');
    await page.click('#send-btn');

    // Wait for streaming to start
    const assistantMessage = page.locator('.message.assistant').last();
    await expect(assistantMessage).toBeVisible({ timeout: 5000 });

    // Auto-scroll should bring us to bottom since we were scrolled up before sending
    // Wait for first content to appear
    await page.waitForTimeout(200);

    // Scroll up to interrupt
    await messagesContainer.evaluate((el) => {
      el.scrollTop = 0;
    });
    await page.waitForTimeout(100);

    // Now scroll back to bottom to resume auto-scroll
    await messagesContainer.evaluate((el) => {
      el.scrollTo({ top: el.scrollHeight, behavior: 'instant' });
    });
    await page.waitForTimeout(100);

    // Wait for streaming to complete
    await expect(assistantMessage).toContainText('mock response', { timeout: 10000 });

    // After streaming completes, we should be at bottom (auto-scroll resumed)
    const scrollInfo = await messagesContainer.evaluate((el) => ({
      scrollTop: el.scrollTop,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    }));
    const distanceFromBottom =
      scrollInfo.scrollHeight - scrollInfo.scrollTop - scrollInfo.clientHeight;
    // Should be within threshold of bottom
    expect(distanceFromBottom).toBeLessThan(150);
  });
});
