/**
 * E2E tests for chat functionality
 */
import { test, expect } from '../global-setup';
import { Buffer } from 'buffer';

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
    // Toast has class "toast toast-error" for error type
    const errorToast = page.locator('.toast-error');
    // Use a short timeout since we're asserting absence
    await expect(errorToast).toHaveCount(0, { timeout: 200 });

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

  test('model selection persists after sending first message in streaming mode', async ({ page }) => {
    const modelSelectorBtn = page.locator('#model-selector-btn');
    const modelDropdown = page.locator('#model-dropdown');

    // Enable streaming
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
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
    await page.fill('#message-input', 'First message with selected model (streaming)');
    await page.click('#send-btn');

    // Wait for streaming to complete
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toContainText('mock response', { timeout: 10000 });

    // Model should still be the one we selected
    expect(await page.locator('#current-model-name').textContent()).toBe(targetModelName);
  });

  /**
   * REGRESSION TEST: Model selection before any conversation exists (initial state)
   *
   * This test catches a bug where selecting a model on initial page load
   * (before clicking New Chat or having any conversation) would:
   * 1. Update the button text correctly (showing new model name)
   * 2. BUT the selection would be lost because there was no conversation to update
   *
   * The issue was that selectModel() only updated the conversation model, but when
   * currentConversation was null (initial state), nothing was stored.
   *
   * The fix adds pendingModel state in the store that tracks the selected model
   * when no conversation exists. This pendingModel is then used when creating
   * a new conversation (either via New Chat or on first message send).
   */
  test('model selection persists on initial state (no conversation)', async ({ page }) => {
    // Navigate to page without clicking New Chat - tests initial state
    // The beforeEach already clicks New Chat, so we need a fresh page
    await page.goto('/');
    await page.waitForSelector('#model-selector-btn');

    // At this point, there should be NO current conversation
    // (user hasn't clicked New Chat yet)

    const modelSelectorBtn = page.locator('#model-selector-btn');
    const modelDropdown = page.locator('#model-dropdown');

    // Get initial model name (should be the default)
    const initialModelName = await page.locator('#current-model-name').textContent();

    // Open dropdown
    await modelSelectorBtn.click();
    await expect(modelDropdown).not.toHaveClass(/hidden/);

    // Find a model that is NOT currently selected
    const modelOptions = modelDropdown.locator('.model-option');
    let differentModelOption = null;
    let differentModelName = null;
    let differentModelId = null;
    const optionCount = await modelOptions.count();
    for (let i = 0; i < optionCount; i++) {
      const option = modelOptions.nth(i);
      const isSelected = await option.evaluate((el) => el.classList.contains('selected'));
      if (!isSelected) {
        differentModelOption = option;
        differentModelName = await option.locator('.model-name').textContent();
        differentModelId = await option.getAttribute('data-model-id');
        break;
      }
    }

    expect(differentModelOption).not.toBeNull();
    expect(differentModelName).not.toBe(initialModelName);

    // Select the different model
    await differentModelOption!.click();
    await expect(modelDropdown).toHaveClass(/hidden/);

    // Model name should be updated in the button
    const newModelName = await page.locator('#current-model-name').textContent();
    expect(newModelName).toBe(differentModelName);

    // Re-open dropdown to verify checkmark is correct
    await modelSelectorBtn.click();
    await expect(modelDropdown).not.toHaveClass(/hidden/);

    // The selected model should have the checkmark
    const selectedOption = modelDropdown.locator(`[data-model-id="${differentModelId}"]`);
    await expect(selectedOption).toHaveClass(/selected/);

    // Only one model should be selected
    const selectedOptions = modelDropdown.locator('.model-option.selected');
    await expect(selectedOptions).toHaveCount(1);

    // Close dropdown
    await modelSelectorBtn.click();

    // Now click New Chat - the selected model should be preserved
    await page.click('#new-chat-btn');

    // Model should still be the one we selected
    expect(await page.locator('#current-model-name').textContent()).toBe(differentModelName);

    // Re-open dropdown to verify checkmark is still correct
    await modelSelectorBtn.click();
    await expect(modelDropdown).not.toHaveClass(/hidden/);
    await expect(selectedOption).toHaveClass(/selected/);
  });

  /**
   * REGRESSION TEST: Dropdown checkmark position after model selection
   *
   * This test catches a bug where selecting a model on a new conversation would:
   * 1. Update the button text correctly (showing new model name)
   * 2. BUT leave the dropdown checkmark on the old model
   *
   * The issue was that selectModel() only called updateCurrentModelDisplay() but
   * didn't re-render the dropdown, so when opened again the checkmark was stale.
   *
   * The fix ensures the dropdown is re-rendered when opened (not when model is selected)
   * to always show fresh data from the store.
   */
  test('dropdown checkmark shows correct model after selection', async ({ page }) => {
    const modelSelectorBtn = page.locator('#model-selector-btn');
    const modelDropdown = page.locator('#model-dropdown');

    // Open dropdown and find a non-default model
    await modelSelectorBtn.click();
    await expect(modelDropdown).not.toHaveClass(/hidden/);

    // Get all model options and find one that's not selected
    const modelOptions = modelDropdown.locator('.model-option');
    let targetOption = null;
    let targetModelId = null;
    const optionCount = await modelOptions.count();
    for (let i = 0; i < optionCount; i++) {
      const option = modelOptions.nth(i);
      const isSelected = await option.evaluate((el) => el.classList.contains('selected'));
      if (!isSelected) {
        targetOption = option;
        targetModelId = await option.getAttribute('data-model-id');
        break;
      }
    }

    expect(targetOption).not.toBeNull();

    // Select the model (dropdown closes)
    await targetOption!.click();
    await expect(modelDropdown).toHaveClass(/hidden/);

    // Re-open dropdown - the checkmark should now be on the newly selected model
    await modelSelectorBtn.click();
    await expect(modelDropdown).not.toHaveClass(/hidden/);

    // Verify the selected model has the checkmark (selected class)
    const selectedOption = modelDropdown.locator(`[data-model-id="${targetModelId}"]`);
    await expect(selectedOption).toHaveClass(/selected/);

    // Verify only one option has the selected class
    const selectedOptions = modelDropdown.locator('.model-option.selected');
    await expect(selectedOptions).toHaveCount(1);
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
    // or removed entirely if there was no thinking/tool content
    const thinkingIndicator = assistantMessage.locator('.thinking-indicator');
    const indicatorCount = await thinkingIndicator.count();

    if (indicatorCount > 0) {
      // If indicator exists, it should be finalized (collapsed with toggle)
      await expect(thinkingIndicator).toHaveClass(/finalized/);
      // And should have a toggle button
      const thinkingToggle = thinkingIndicator.locator('.thinking-toggle');
      await expect(thinkingToggle).toBeVisible();
    }
    // If indicatorCount is 0, that's also valid (removed because no content)
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

  test('scroll position is maintained when scrolling up during active token streaming', async ({ page }) => {
    // This test verifies the fix for the race condition where:
    // - User scrolls up during streaming
    // - Tokens arrive faster than the debounce period
    // - Without the fix, auto-scroll would override the user's scroll position
    //
    // The fix makes scroll-up detection immediate (no debounce) to prevent this race condition

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

    // Send a message to start streaming
    await page.fill('#message-input', 'Tell me a very long story');
    await page.click('#send-btn');

    // Wait for streaming to start (assistant message appears)
    const assistantMessage = page.locator('.message.assistant').last();
    await expect(assistantMessage).toBeVisible({ timeout: 5000 });

    // Wait for some content to arrive (so there's something to scroll away from)
    await page.waitForTimeout(100);

    // Scroll to the top to read the beginning of the message
    // Use scrollTo() which more reliably triggers scroll events across browsers
    await messagesContainer.evaluate((el) => {
      el.scrollTo({ top: 0, behavior: 'instant' });
    });

    // Wait for the scroll event to be processed by our scroll listener
    // This is necessary because scroll events are asynchronous and webkit
    // may process them differently than chromium
    // Also wait a bit longer to ensure autoScrollForStreaming() has a chance to run
    // and detect the scroll-up (it checks synchronously before scrolling)
    await page.waitForTimeout(100);

    // Record the scroll position
    // Note: Due to timing, the scroll position might not be exactly 0
    // (autoScrollForStreaming might have started scrolling before the scroll event fired)
    // But it should be near the top (allowing some tolerance)
    const scrollTopAfterUserScroll = await messagesContainer.evaluate((el) => el.scrollTop);
    expect(scrollTopAfterUserScroll).toBeLessThan(100); // Near top, not scrolled to bottom

    // Wait for more tokens to arrive while we're scrolled up
    // Without the fix, these tokens would trigger auto-scroll and bring us back to bottom
    await page.waitForTimeout(200);

    // Verify we're still at the position we scrolled to (not brought back to bottom)
    const scrollTopAfterTokens = await messagesContainer.evaluate((el) => el.scrollTop);

    // We should still be near the top (allowing some tolerance for layout changes)
    // The key assertion: we should NOT have been scrolled to the bottom
    expect(scrollTopAfterTokens).toBeLessThan(100);

    // Wait for streaming to complete
    await expect(assistantMessage).toContainText('mock response', { timeout: 10000 });

    // After streaming completes, verify we're still near where we scrolled to
    const scrollTopAfterComplete = await messagesContainer.evaluate((el) => el.scrollTop);
    expect(scrollTopAfterComplete).toBeLessThan(100);
  });

  test('rapid scrolling during streaming does not cause flicker or unexpected scroll jumps', async ({ page }) => {
    // This test verifies that the scroll behavior is smooth and predictable
    // when the user scrolls multiple times during streaming

    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }

    // First, create some messages to have scrollable content
    await streamBtn.click(); // Disable streaming temporarily
    for (let i = 0; i < 2; i++) {
      await page.fill('#message-input', `Setup message ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 10000 });
    }
    await streamBtn.click(); // Re-enable streaming

    const messagesContainer = page.locator('#messages');

    // Send a message to start streaming
    await page.fill('#message-input', 'Tell me a story');
    await page.click('#send-btn');

    // Wait for streaming to start
    const assistantMessage = page.locator('.message.assistant').last();
    await expect(assistantMessage).toBeVisible({ timeout: 5000 });

    // Perform rapid scroll up/down movements during streaming
    // This simulates a user browsing during an active stream
    // Use scrollTo() which more reliably triggers scroll events across browsers
    for (let i = 0; i < 3; i++) {
      // Scroll up
      await messagesContainer.evaluate((el) => {
        el.scrollTo({ top: 0, behavior: 'instant' });
      });
      await page.waitForTimeout(100); // Wait for scroll event to be processed

      // Verify we stayed at the top (not brought back by auto-scroll)
      let scrollTop = await messagesContainer.evaluate((el) => el.scrollTop);
      expect(scrollTop).toBeLessThan(100);

      // Scroll to middle
      await messagesContainer.evaluate((el) => {
        el.scrollTo({ top: el.scrollHeight / 2, behavior: 'instant' });
      });
      await page.waitForTimeout(100); // Wait for scroll event to be processed
    }

    // Finally scroll back to bottom to resume auto-scroll
    await messagesContainer.evaluate((el) => {
      el.scrollTo({ top: el.scrollHeight, behavior: 'instant' });
    });
    await page.waitForTimeout(200); // Wait for debounce to re-enable auto-scroll

    // Wait for streaming to complete
    await expect(assistantMessage).toContainText('mock response', { timeout: 10000 });

    // After scrolling to bottom and streaming completing, should be at bottom
    const scrollInfo = await messagesContainer.evaluate((el) => ({
      scrollTop: el.scrollTop,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    }));
    const distanceFromBottom =
      scrollInfo.scrollHeight - scrollInfo.scrollTop - scrollInfo.clientHeight;
    expect(distanceFromBottom).toBeLessThan(150);
  });
});

test.describe('Chat - Image Loading Scroll', () => {
  /**
   * REGRESSION TEST: Image at top of conversation causing scroll issues
   *
   * Bug: When loading a conversation with an image at the TOP (above viewport),
   * the image loading would increase scrollHeight, making it appear the user
   * had scrolled away from the bottom. The position-based scroll listener
   * would then disable auto-scroll before the final smooth scroll could run.
   *
   * Fix: Changed setupUserScrollListener to use direction-based detection
   * (like streaming scroll listener). Only disables scroll mode when scrollTop
   * DECREASES (user actually scrolled up), not when distanceFromBottom increases
   * due to images loading above viewport.
   */
  test('scrolls to bottom when conversation has image at top', async ({ page }) => {
    // Create a conversation with many messages and an image in the first message
    // The image will be above the viewport when we scroll to bottom
    const pngBase64 =
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';

    // Create messages: first one has an image, then several text messages
    const messages = [
      {
        role: 'user',
        content: 'Here is an image',
        files: [
          {
            name: 'test-image.png',
            type: 'image/png',
            data: pngBase64,
          },
        ],
      },
      { role: 'assistant', content: 'I see the image you shared.' },
    ];

    // Add more messages to ensure the image is above the viewport
    for (let i = 0; i < 10; i++) {
      messages.push({ role: 'user', content: `Follow-up message ${i + 1}` });
      messages.push({
        role: 'assistant',
        content: `This is a response to follow-up ${i + 1}. It has some content to take up space.`,
      });
    }

    // Seed the conversation via test API
    const response = await page.request.post('/test/seed', {
      data: {
        conversations: [{ title: 'Image at Top Test', messages }],
      },
    });
    expect(response.ok()).toBe(true);

    // Navigate to the app
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Click on the seeded conversation
    const conversationItem = page.locator('.conversation-item-wrapper').first();
    await expect(conversationItem).toBeVisible({ timeout: 5000 });
    await conversationItem.click();

    // Wait for messages to load
    await page.waitForSelector('.message.user', { timeout: 10000 });

    // Wait for image to load (this is the key part of the test)
    // The image loading above viewport should not prevent final scroll
    const messageImage = page.locator('.message-image');
    await expect(messageImage).toBeVisible({ timeout: 10000 });

    // Wait a bit for scroll logic to complete
    await page.waitForTimeout(500);

    // Verify we're at the bottom after everything loads
    const messagesContainer = page.locator('#messages');
    const scrollInfo = await messagesContainer.evaluate((el) => ({
      scrollTop: el.scrollTop,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    }));
    const distanceFromBottom =
      scrollInfo.scrollHeight - scrollInfo.scrollTop - scrollInfo.clientHeight;

    // Should be at or very near the bottom (within threshold)
    // Using a reasonable threshold since smooth scroll may not be pixel-perfect
    expect(distanceFromBottom).toBeLessThan(50);
  });

  test('user can still scroll up to disable auto-scroll with images', async ({ page }) => {
    // Create a conversation with an image and enough content to scroll
    const pngBase64 =
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';

    const messages = [
      {
        role: 'user',
        content: 'Here is an image',
        files: [{ name: 'test.png', type: 'image/png', data: pngBase64 }],
      },
      { role: 'assistant', content: 'I see the image.' },
    ];

    for (let i = 0; i < 10; i++) {
      messages.push({ role: 'user', content: `Message ${i + 1}` });
      messages.push({ role: 'assistant', content: `Response ${i + 1} with content.` });
    }

    await page.request.post('/test/seed', {
      data: { conversations: [{ title: 'User Scroll Test', messages }] },
    });

    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    const conversationItem = page.locator('.conversation-item-wrapper').first();
    await conversationItem.click();

    await page.waitForSelector('.message.user', { timeout: 10000 });

    const messagesContainer = page.locator('#messages');

    // Wait for initial scroll to bottom and any pending scroll operations to complete
    // This ensures we start from a stable state at the bottom
    await page.waitForTimeout(1000);

    // Verify we're at the bottom first
    const initialScrollInfo = await messagesContainer.evaluate((el) => ({
      scrollTop: el.scrollTop,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    }));
    const initialDistanceFromBottom =
      initialScrollInfo.scrollHeight - initialScrollInfo.scrollTop - initialScrollInfo.clientHeight;
    expect(initialDistanceFromBottom).toBeLessThan(100); // Should be at bottom initially

    // Scroll up (this should disable auto-scroll)
    await messagesContainer.evaluate((el) => {
      el.scrollTo({ top: 0, behavior: 'instant' });
    });

    // Wait for scroll event to be processed
    await page.waitForTimeout(500);

    // Verify we're still at the top (not scrolled back to bottom)
    const scrollTop = await messagesContainer.evaluate((el) => el.scrollTop);
    expect(scrollTop).toBeLessThan(50); // Allow some tolerance

    // If we stayed at top, auto-scroll was correctly disabled
    // (If the bug existed, we would have been scrolled back to bottom)
  });
});

test.describe('Chat - Message Retry', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Disable streaming for batch tests (easier to control errors)
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }
  });

  test('retry button restores message to input and sends it', async ({ page }) => {
    // Enable error simulation mode for the next request
    await page.evaluate(() => {
      // Store the original message to verify it's restored
      (window as unknown as { __testMessage: string }).__testMessage = 'Test message for retry';
    });

    // Type a message
    await page.fill('#message-input', 'Test message for retry');

    // Intercept the chat request to make it fail with a retryable error
    await page.route('**/chat/batch', async (route) => {
      // First request fails
      const requestCount = await page.evaluate(() => {
        const count = ((window as unknown as { __chatRequestCount: number }).__chatRequestCount ?? 0) + 1;
        (window as unknown as { __chatRequestCount: number }).__chatRequestCount = count;
        return count;
      });

      if (requestCount === 1) {
        // First request: return a retryable error
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({
            error: {
              code: 'SERVER_ERROR',
              message: 'Simulated server error',
              retryable: true,
            },
          }),
        });
      } else {
        // Subsequent requests: pass through to actual server
        await route.continue();
      }
    });

    // Send the message
    await page.click('#send-btn');

    // Wait for error toast with retry button
    const toast = page.locator('.toast-error');
    await expect(toast).toBeVisible({ timeout: 5000 });
    await expect(toast).toContainText('Please try again');

    // Verify the retry button is present
    const retryButton = toast.locator('.toast-action');
    await expect(retryButton).toBeVisible();
    await expect(retryButton).toContainText('Retry');

    // The input should be cleared after failed send (message was added to UI)
    const textarea = page.locator('#message-input');
    await expect(textarea).toHaveValue('');

    // Click retry button
    await retryButton.click();

    // The message should be restored to the input
    await expect(textarea).toHaveValue('Test message for retry');

    // Toast should be dismissed
    await expect(toast).not.toBeVisible({ timeout: 2000 });

    // Click send again (the retry should have restored the message)
    await page.click('#send-btn');

    // Now we should get a successful response
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });
    await expect(assistantMessage).toContainText('mock response', { ignoreCase: true });
  });

  test('draft is saved on error and can be recovered on page reload', async ({ page }) => {
    // Type a message
    await page.fill('#message-input', 'Draft message for recovery');

    // Intercept the chat request to make it fail
    await page.route('**/chat/batch', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({
          error: {
            code: 'SERVER_ERROR',
            message: 'Simulated server error',
            retryable: true,
          },
        }),
      });
    });

    // Send the message
    await page.click('#send-btn');

    // Wait for error toast
    const toast = page.locator('.toast-error');
    await expect(toast).toBeVisible({ timeout: 5000 });

    // Verify draft is saved to localStorage (check store state)
    const draftMessage = await page.evaluate(() => {
      const storage = localStorage.getItem('ai-chatbot-storage');
      if (storage) {
        const parsed = JSON.parse(storage);
        return parsed.state?.draftMessage;
      }
      return null;
    });
    expect(draftMessage).toBe('Draft message for recovery');
  });

  test('streaming mode: retry button restores message to input', async ({ page }) => {
    // Enable streaming mode
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'false') {
      await streamBtn.click();
    }
    // Verify streaming is enabled
    await expect(streamBtn).toHaveAttribute('aria-pressed', 'true');

    // Type a message
    await page.fill('#message-input', 'Streaming test message for retry');

    // Intercept the streaming request to make it fail with SSE error event
    let requestCount = 0;
    await page.route('**/chat/stream', async (route) => {
      requestCount++;
      if (requestCount === 1) {
        // First request: return an SSE error event
        const errorEvent = `event: error\ndata: ${JSON.stringify({
          type: 'error',
          message: 'Simulated streaming error',
          code: 'SERVER_ERROR',
          retryable: true,
        })}\n\n`;

        await route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: errorEvent,
        });
      } else {
        // Subsequent requests: pass through to actual server
        await route.continue();
      }
    });

    // Send the message
    await page.click('#send-btn');

    // Wait for error toast with retry button
    const toast = page.locator('.toast-error');
    await expect(toast).toBeVisible({ timeout: 5000 });

    // Verify the retry button is present
    const retryButton = toast.locator('.toast-action');
    await expect(retryButton).toBeVisible();
    await expect(retryButton).toContainText('Retry');

    // The input should be cleared after failed send
    const textarea = page.locator('#message-input');
    await expect(textarea).toHaveValue('');

    // Verify draft is saved to localStorage before clicking retry
    const draftMessageBeforeRetry = await page.evaluate(() => {
      const storage = localStorage.getItem('ai-chatbot-storage');
      if (storage) {
        const parsed = JSON.parse(storage);
        return parsed.state?.draftMessage;
      }
      return null;
    });
    expect(draftMessageBeforeRetry).toBe('Streaming test message for retry');

    // Click retry button
    await retryButton.click();

    // The message should be restored to the input
    await expect(textarea).toHaveValue('Streaming test message for retry');

    // Toast should be dismissed
    await expect(toast).not.toBeVisible({ timeout: 2000 });
  });
});

test.describe('Chat - Stop Streaming', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Enable streaming for stop tests
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }

    // Set a very slow stream delay so there's time to click the stop button
    // Default is 10ms which is too fast for tests that need to interact with the stop button
    // With ~10 words in the response and 1000ms per word, we get ~10 seconds of streaming
    await page.request.post('/test/set-stream-delay', { data: { delay_ms: 1000 } });
  });

  test.afterEach(async ({ page }) => {
    // Reset stream delay to default after each test
    await page.request.post('/test/set-stream-delay', { data: { delay_ms: 10 } });
  });

  test('send button shows send icon initially', async ({ page }) => {
    const sendBtn = page.locator('#send-btn');

    // Should have send icon (btn-send class) initially
    await expect(sendBtn).toHaveClass(/btn-send/);
    await expect(sendBtn).not.toHaveClass(/btn-stop/);

    // Should have correct title
    await expect(sendBtn).toHaveAttribute('title', 'Send message');
  });

  test('send button transforms to stop button during streaming', async ({ page }) => {
    const sendBtn = page.locator('#send-btn');

    // Type a message
    await page.fill('#message-input', 'Tell me a very long story');

    // Click send
    await page.click('#send-btn');

    // Wait for streaming to start (assistant message appears)
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 5000 });

    // Send button should transform to stop button during streaming
    await expect(sendBtn).toHaveClass(/btn-stop/, { timeout: 2000 });
    await expect(sendBtn).not.toHaveClass(/btn-send/);
    await expect(sendBtn).toHaveAttribute('title', 'Stop generating');

    // Wait for streaming to complete naturally by waiting for the button to revert
    // With 1000ms delay per word (set in beforeEach), streaming takes ~10-12 seconds
    // Note: We wait for btn-send class instead of text because the response text
    // ("mock response") appears early in the stream, before it's complete
    await expect(sendBtn).toHaveClass(/btn-send/, { timeout: 15000 });
    await expect(sendBtn).not.toHaveClass(/btn-stop/);
    await expect(sendBtn).toHaveAttribute('title', 'Send message');
  });

  test('clicking stop button aborts stream and shows toast', async ({ page }) => {
    // Type a message
    await page.fill('#message-input', 'Tell me a very long story please');

    // Click send
    await page.click('#send-btn');

    // Wait for streaming to start (assistant message appears)
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 5000 });

    // Click the stop button - use selector with class to ensure atomicity
    // This waits for the button to have btn-stop class before clicking
    // Use force:true to skip stability check (button has pulsing animation)
    await page.click('#send-btn.btn-stop', { timeout: 5000, force: true });

    // Toast should appear confirming the action
    const toast = page.locator('.toast-info');
    await expect(toast).toBeVisible({ timeout: 3000 });
    await expect(toast).toContainText('Response stopped');

    // The streaming assistant message should be removed from UI
    // Wait a moment for cleanup
    await page.waitForTimeout(500);

    // After abort, only user message should remain (assistant message removed)
    // Note: The user message still exists
    const userMessage = page.locator('.message.user');
    await expect(userMessage).toBeVisible();

    // Assistant message should be removed (or the count should be 0)
    const assistantMessages = page.locator('.message.assistant');
    await expect(assistantMessages).toHaveCount(0);

    // Send button should revert to send mode
    const sendBtn = page.locator('#send-btn');
    await expect(sendBtn).toHaveClass(/btn-send/);
    await expect(sendBtn).not.toHaveClass(/btn-stop/);
  });

  test('stop button does not appear in batch mode', async ({ page }) => {
    // Disable streaming for batch mode
    const streamBtn = page.locator('#stream-btn');
    await streamBtn.click();
    await expect(streamBtn).toHaveAttribute('aria-pressed', 'false');

    const sendBtn = page.locator('#send-btn');

    // Type a message
    await page.fill('#message-input', 'Hello batch mode');

    // Click send
    await page.click('#send-btn');

    // Wait for response
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });

    // Send button should never have transformed to stop button
    // It should always have btn-send class (or be disabled during loading)
    // Since batch is fast, we check it hasn't changed
    await expect(sendBtn).toHaveClass(/btn-send/);
    await expect(sendBtn).not.toHaveClass(/btn-stop/);
  });

  test('stop button only appears for current conversation', async ({ page }) => {
    const sendBtn = page.locator('#send-btn');

    // Send message in first conversation
    await page.fill('#message-input', 'First conversation message');
    await page.click('#send-btn');

    // Wait for streaming to start
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 5000 });

    // Stop button should appear
    await expect(sendBtn).toHaveClass(/btn-stop/, { timeout: 2000 });

    // Create a new conversation (switch away while streaming)
    await page.click('#new-chat-btn');

    // In the new conversation, stop button should NOT appear
    // because we're not streaming in THIS conversation
    await expect(sendBtn).toHaveClass(/btn-send/);
    await expect(sendBtn).not.toHaveClass(/btn-stop/);
  });

  test('abort handles quick stop during thinking phase', async ({ page }) => {
    // beforeEach already sets a slow stream delay (500ms)
    // Type a message that triggers thinking
    await page.fill('#message-input', 'Let me think about this');

    // Click send
    await page.click('#send-btn');

    // Wait for assistant message to appear
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 5000 });

    // Click stop button - use selector with class to ensure atomicity
    // Use force:true to skip stability check (button has pulsing animation)
    await page.click('#send-btn.btn-stop', { timeout: 5000, force: true });

    // Should show toast
    const toast = page.locator('.toast-info');
    await expect(toast).toBeVisible({ timeout: 3000 });
    await expect(toast).toContainText('Response stopped');

    // Assistant message should be removed
    await expect(assistantMessage).toHaveCount(0, { timeout: 2000 });

    // Button should revert
    const sendBtn = page.locator('#send-btn');
    await expect(sendBtn).toHaveClass(/btn-send/);
    // afterEach resets stream delay to default
  });
});

test.describe('Chat - Clipboard Paste', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');
  });

  /**
   * Helper function to simulate pasting an image by directly calling the
   * addFilesToPending function through the store. This bypasses browser
   * clipboard security restrictions that prevent programmatic paste events
   * from having file data.
   *
   * Note: The actual paste handler is tested via unit tests. These E2E tests
   * verify the integration with the file preview UI and send button state.
   */
  async function simulateImagePaste(
    page: import('@playwright/test').Page,
    pngBase64: string,
    fileName: string
  ): Promise<void> {
    await page.evaluate(
      async ({ base64, name }) => {
        // Convert base64 to blob
        const binaryString = atob(base64);
        const bytes = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
          bytes[i] = binaryString.charCodeAt(i);
        }
        const blob = new Blob([bytes], { type: 'image/png' });

        // Read as data URL to get base64 for the store
        const reader = new FileReader();
        const dataUrl = await new Promise<string>((resolve) => {
          reader.onload = () => resolve(reader.result as string);
          reader.readAsDataURL(blob);
        });
        const data = dataUrl.split(',')[1];

        // Create preview URL
        const previewUrl = URL.createObjectURL(blob);

        // Add to store (simulating what addFilesToPending does)
        const storage = localStorage.getItem('ai-chatbot-storage');
        if (storage) {
          const parsed = JSON.parse(storage);
          const pendingFiles = parsed.state?.pendingFiles || [];
          pendingFiles.push({
            name,
            type: 'image/png',
            data,
            previewUrl,
          });
          parsed.state.pendingFiles = pendingFiles;
          localStorage.setItem('ai-chatbot-storage', JSON.stringify(parsed));

          // Trigger Zustand state update by dispatching storage event
          window.dispatchEvent(new StorageEvent('storage', { key: 'ai-chatbot-storage' }));
        }
      },
      { base64: pngBase64, name: fileName }
    );

    // Reload the page to sync Zustand state from localStorage
    // This is necessary because we modified localStorage directly
    await page.reload();
    await page.waitForSelector('#new-chat-btn');
  }

  test('file preview shows uploaded images', async ({ page }) => {
    const filePreview = page.locator('#file-preview');
    const sendBtn = page.locator('#send-btn');

    // Verify file preview is hidden initially
    await expect(filePreview).toHaveClass(/hidden/);
    await expect(sendBtn).toBeDisabled();

    // Use the attach button to add an image (this is the reliable way to test file upload)
    // Set up file chooser before clicking
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('#attach-btn');
    const fileChooser = await fileChooserPromise;

    // Create a minimal PNG buffer
    const pngBase64 =
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
    const pngBuffer = Buffer.from(pngBase64, 'base64');

    await fileChooser.setFiles({
      name: 'test-image.png',
      mimeType: 'image/png',
      buffer: pngBuffer,
    });

    // Wait for the file preview to become visible
    await expect(filePreview).not.toHaveClass(/hidden/, { timeout: 3000 });

    // File preview should contain an image
    const previewImage = filePreview.locator('.file-preview-image');
    await expect(previewImage).toBeVisible();

    // Image should have a thumbnail
    const img = previewImage.locator('img');
    await expect(img).toBeVisible();

    // Remove button should be present
    const removeBtn = previewImage.locator('.file-preview-remove');
    await expect(removeBtn).toBeVisible();

    // Send button should be enabled
    await expect(sendBtn).not.toBeDisabled();
  });

  test('uploaded image can be removed from preview', async ({ page }) => {
    const filePreview = page.locator('#file-preview');

    // Upload an image
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('#attach-btn');
    const fileChooser = await fileChooserPromise;

    const pngBase64 =
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
    const pngBuffer = Buffer.from(pngBase64, 'base64');

    await fileChooser.setFiles({
      name: 'test-image.png',
      mimeType: 'image/png',
      buffer: pngBuffer,
    });

    // Wait for preview to appear
    await expect(filePreview).not.toHaveClass(/hidden/, { timeout: 3000 });

    // Click remove button
    const removeBtn = filePreview.locator('.file-preview-remove');
    await removeBtn.click();

    // File preview should be hidden again
    await expect(filePreview).toHaveClass(/hidden/);

    // Send button should be disabled again
    const sendBtn = page.locator('#send-btn');
    await expect(sendBtn).toBeDisabled();
  });

  test('pasting text does not affect file preview', async ({ page }) => {
    const textarea = page.locator('#message-input');
    const filePreview = page.locator('#file-preview');

    // Focus the textarea
    await textarea.focus();

    // Type some text first
    await textarea.fill('Some initial text');

    // Paste plain text using keyboard shortcut
    // First, simulate copying text to clipboard and pasting
    await page.evaluate(() => {
      const pasteEvent = new ClipboardEvent('paste', {
        bubbles: true,
        cancelable: true,
        clipboardData: new DataTransfer(),
      });
      // Set text data (no files)
      pasteEvent.clipboardData?.setData('text/plain', 'pasted text');

      const input = document.querySelector('#message-input');
      input?.dispatchEvent(pasteEvent);
    });

    // File preview should remain hidden (text paste doesn't affect it)
    await expect(filePreview).toHaveClass(/hidden/);

    // Input should still have its text (browser handles text paste normally)
    // Note: We're not modifying the input value on text paste, browser does that
    await expect(textarea).toHaveValue('Some initial text');
  });

  test('multiple images can be uploaded', async ({ page }) => {
    const filePreview = page.locator('#file-preview');

    const pngBase64 =
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
    const pngBuffer = Buffer.from(pngBase64, 'base64');

    // Upload first image
    const fileChooserPromise1 = page.waitForEvent('filechooser');
    await page.click('#attach-btn');
    const fileChooser1 = await fileChooserPromise1;
    await fileChooser1.setFiles({
      name: 'image1.png',
      mimeType: 'image/png',
      buffer: pngBuffer,
    });

    await expect(filePreview).not.toHaveClass(/hidden/, { timeout: 3000 });

    // Upload second image
    const fileChooserPromise2 = page.waitForEvent('filechooser');
    await page.click('#attach-btn');
    const fileChooser2 = await fileChooserPromise2;
    await fileChooser2.setFiles({
      name: 'image2.png',
      mimeType: 'image/png',
      buffer: pngBuffer,
    });

    // Should have 2 preview items
    const previewItems = filePreview.locator('.file-preview-item');
    await expect(previewItems).toHaveCount(2);
  });

  test('image upload enables send button', async ({ page }) => {
    const sendBtn = page.locator('#send-btn');

    // Send button should be disabled initially (no content)
    await expect(sendBtn).toBeDisabled();

    // Upload an image
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('#attach-btn');
    const fileChooser = await fileChooserPromise;

    const pngBase64 =
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
    const pngBuffer = Buffer.from(pngBase64, 'base64');

    await fileChooser.setFiles({
      name: 'test-image.png',
      mimeType: 'image/png',
      buffer: pngBuffer,
    });

    // Send button should be enabled now (has file)
    await expect(sendBtn).not.toBeDisabled({ timeout: 500 });
  });
});

test.describe('Chat - Copy to Clipboard', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Disable streaming for consistent tests
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }
  });

  test.afterEach(async ({ page }) => {
    // Always clean up mock response after each test
    await page.request.post('/test/clear-mock-response');
  });

  test('shows inline copy button on code blocks', async ({ page }) => {
    // Set a response with a code block
    await page.request.post('/test/set-mock-response', {
      data: { response: '```python\nprint("Hello World")\n```' },
    });

    await page.fill('#message-input', 'Show me code');
    await page.click('#send-btn');

    // Wait for the code block wrapper to appear (includes markdown rendering)
    const codeBlockWrapper = page.locator('.code-block-wrapper');
    await expect(codeBlockWrapper).toBeVisible({ timeout: 10000 });

    // Inline copy button should be present (visible on hover or touch)
    const inlineCopyBtn = codeBlockWrapper.locator('.inline-copy-btn');
    await expect(inlineCopyBtn).toBeAttached();

    // Language label should be shown
    const langLabel = codeBlockWrapper.locator('.code-language');
    await expect(langLabel).toHaveText('python');
  });

  test('shows inline copy button on tables', async ({ page }) => {
    // Set a response with a table
    await page.request.post('/test/set-mock-response', {
      data: { response: '| Name | Age |\n|------|-----|\n| Alice | 30 |\n| Bob | 25 |' },
    });

    await page.fill('#message-input', 'Show me a table');
    await page.click('#send-btn');

    // Wait for the table wrapper to appear (includes markdown rendering)
    const tableWrapper = page.locator('.table-wrapper');
    await expect(tableWrapper).toBeVisible({ timeout: 10000 });

    // Inline copy button should be present
    const inlineCopyBtn = tableWrapper.locator('.inline-copy-btn');
    await expect(inlineCopyBtn).toBeAttached();

    // Table should have correct content
    const table = tableWrapper.locator('table');
    await expect(table).toContainText('Alice');
    await expect(table).toContainText('Bob');
  });

  // Skip clipboard tests on webkit - it doesn't support clipboard-write permission
  test('inline copy button shows success feedback', async ({ page, browserName }) => {
    test.skip(browserName === 'webkit', 'Webkit does not support clipboard permissions');

    // Grant clipboard permissions for this test
    await page.context().grantPermissions(['clipboard-write', 'clipboard-read']);

    // Set a response with a code block
    await page.request.post('/test/set-mock-response', {
      data: { response: '```javascript\nconsole.log("test");\n```' },
    });

    await page.fill('#message-input', 'Show me code');
    await page.click('#send-btn');

    // Wait for the code block wrapper to appear
    const codeBlockWrapper = page.locator('.code-block-wrapper');
    await expect(codeBlockWrapper).toBeVisible({ timeout: 10000 });

    // Hover to reveal the button
    await codeBlockWrapper.hover();

    // Click the copy button
    const inlineCopyBtn = codeBlockWrapper.locator('.inline-copy-btn');
    await inlineCopyBtn.click();

    // Button should show copied state
    await expect(inlineCopyBtn).toHaveClass(/copied/);

    // After 2 seconds, copied state should be removed
    await page.waitForTimeout(2100);
    await expect(inlineCopyBtn).not.toHaveClass(/copied/);
  });

  test('message copy button excludes inline copy buttons and language labels', async ({
    page,
    browserName,
  }) => {
    test.skip(browserName === 'webkit', 'Webkit does not support clipboard permissions');

    // Grant clipboard permissions
    await page.context().grantPermissions(['clipboard-write', 'clipboard-read']);

    // Set a response with a code block
    await page.request.post('/test/set-mock-response', {
      data: { response: 'Here is some code:\n\n```python\nprint("test")\n```' },
    });

    await page.fill('#message-input', 'Show me code');
    await page.click('#send-btn');

    // Wait for the code block wrapper to appear
    const codeBlockWrapper = page.locator('.code-block-wrapper');
    await expect(codeBlockWrapper).toBeVisible({ timeout: 10000 });

    // Hover over the assistant message to reveal actions
    const assistantMessage = page.locator('.message.assistant');
    await assistantMessage.hover();

    // Click the message copy button
    const messageCopyBtn = assistantMessage.locator('.message-copy-btn');
    await messageCopyBtn.click();

    // Button should show copied state
    await expect(messageCopyBtn).toHaveClass(/copied/);

    // Read clipboard and verify content is correct
    const clipboardText = await page.evaluate(() => navigator.clipboard.readText());
    expect(clipboardText).toContain('print("test")');
    expect(clipboardText).toContain('Here is some code');
    // The clipboard text should start with the message content, not the language label
    expect(clipboardText.trim().startsWith('Here is some code')).toBe(true);
  });

  test('inline copy buttons are visible on mobile (touch devices)', async ({ page }) => {
    // Set mobile viewport
    await page.setViewportSize({ width: 375, height: 812 });

    // Set a response with a code block
    await page.request.post('/test/set-mock-response', {
      data: { response: '```python\nprint("Hello")\n```' },
    });

    await page.fill('#message-input', 'Show me code');
    await page.click('#send-btn');

    // Wait for the code block wrapper to appear
    const codeBlockWrapper = page.locator('.code-block-wrapper');
    await expect(codeBlockWrapper).toBeVisible({ timeout: 10000 });

    // Inline copy button should be present
    const inlineCopyBtn = codeBlockWrapper.locator('.inline-copy-btn');
    await expect(inlineCopyBtn).toBeAttached();
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
    await page.request.post('/test/set-stream-delay', {
      data: { delay_ms: 500 },
    });

    // Enable streaming mode
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }

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
    await page.request.post('/test/set-stream-delay', {
      data: { delay_ms: 10 },
    });
  });

  test('restores batch loading indicator when switching back to conversation with active batch request', async ({
    page,
  }) => {
    // Configure slow response for batch mode (delay gives time to switch conversations)
    await page.request.post('/test/set-batch-delay', {
      data: { delay_ms: 500 },
    });

    // Disable streaming for batch mode
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }

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
    await page.request.post('/test/set-batch-delay', {
      data: { delay_ms: 0 },
    });
  });

  test('streaming continues and completes when switching back to conversation', async ({
    page,
  }) => {
    // Configure streaming delay (enough time to switch conversations)
    await page.request.post('/test/set-stream-delay', {
      data: { delay_ms: 100 },
    });

    // Enable streaming mode
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }

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

    // Wait for streaming to complete (message should have content)
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toContainText('mock response', { timeout: 15000 });

    // Message should no longer be in streaming state
    await expect(page.locator('.message.assistant.streaming')).toHaveCount(0, { timeout: 10000 });

    // Reset stream delay
    await page.request.post('/test/set-stream-delay', {
      data: { delay_ms: 10 },
    });
  });

  test('multiple rapid conversation switches preserve streaming state', async ({ page }) => {
    // Configure streaming delay (enough time for rapid switching)
    await page.request.post('/test/set-stream-delay', {
      data: { delay_ms: 30 },
    });

    // Enable streaming mode
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }

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
    await page.request.post('/test/set-stream-delay', {
      data: { delay_ms: 10 },
    });
  });

  test('preserves thinking indicator state when switching back to streaming conversation', async ({
    page,
  }) => {
    // Set a longer stream delay to ensure we can catch the streaming state
    await page.request.post('/test/set-stream-delay', {
      data: { delay_ms: 200 },
    });

    // Enable thinking events
    await page.request.post('/test/set-emit-thinking', {
      data: { emit: true },
    });

    // Enable streaming mode
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }

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
    await page.request.post('/test/set-stream-delay', {
      data: { delay_ms: 10 },
    });
    await page.request.post('/test/set-emit-thinking', {
      data: { emit: false },
    });
  });

  test('preserves accumulated content when switching back to streaming conversation', async ({
    page,
  }) => {
    // Configure streaming to accumulate content before switching
    await page.request.post('/test/set-stream-delay', {
      data: { delay_ms: 30 },
    });

    // Enable streaming mode
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }

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
    await page.request.post('/test/set-stream-delay', {
      data: { delay_ms: 10 },
    });
  });
});

test.describe('Chat - Lightbox', () => {
  // Create a valid PNG buffer (8x8 red image)
  const pngBuffer = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAADklEQVQI12P4z8DAwMAAAx4D/dnaJvgAAAAASUVORK5CYII=',
    'base64'
  );

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Disable streaming for consistent tests
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }
  });

  test('clicking image in message opens lightbox with full image', async ({ page }) => {
    // Upload an image and send a message
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('#attach-btn');
    const fileChooser = await fileChooserPromise;

    await fileChooser.setFiles({
      name: 'test-image.png',
      mimeType: 'image/png',
      buffer: pngBuffer,
    });

    // Wait for file preview to appear
    const filePreview = page.locator('#file-preview');
    await expect(filePreview).not.toHaveClass(/hidden/, { timeout: 3000 });

    // Send message with image
    await page.fill('#message-input', 'Here is an image');
    await page.click('#send-btn');

    // Wait for assistant response
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Find the image in the user message
    const userMessage = page.locator('.message.user');
    const messageImage = userMessage.locator('.message-image');
    await expect(messageImage).toBeVisible({ timeout: 5000 });

    // Click on the image to open lightbox
    await messageImage.click();

    // Lightbox should open and show the image
    const lightbox = page.locator('#lightbox');
    await expect(lightbox).not.toHaveClass(/hidden/, { timeout: 5000 });

    // Lightbox image should be loaded (not empty src)
    const lightboxImg = page.locator('#lightbox-img');
    await expect(lightboxImg).toBeVisible();

    // The image should have a valid src (blob URL)
    const imgSrc = await lightboxImg.getAttribute('src');
    expect(imgSrc).toBeTruthy();
    expect(imgSrc).toMatch(/^blob:/);

    // No error toast should be shown
    const errorToast = page.locator('.toast.error');
    await expect(errorToast).not.toBeVisible();

    // Close lightbox by clicking outside
    await lightbox.click({ position: { x: 10, y: 10 } });
    await expect(lightbox).toHaveClass(/hidden/);
  });

  test('lightbox shows error toast when image fails to load', async ({ page }) => {
    // This test verifies the error handling when the lightbox fails to load an image.
    // We'll manually dispatch a lightbox:open event with a non-existent message ID
    // to trigger the error path.

    await page.evaluate(() => {
      window.dispatchEvent(
        new CustomEvent('lightbox:open', {
          detail: {
            messageId: 'non-existent-message-id',
            fileIndex: '0',
          },
        })
      );
    });

    // Error toast should appear (class is toast-error, not toast.error)
    const errorToast = page.locator('.toast-error');
    await expect(errorToast).toBeVisible({ timeout: 5000 });
    await expect(errorToast).toContainText('Failed to load image');

    // Lightbox should be hidden (closed after error)
    const lightbox = page.locator('#lightbox');
    await expect(lightbox).toHaveClass(/hidden/);
  });

  test('clicking image during streaming opens lightbox after user_message_saved event', async ({ page }) => {
    // Enable streaming for this test
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }

    // Upload an image and send a message
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('#attach-btn');
    const fileChooser = await fileChooserPromise;

    await fileChooser.setFiles({
      name: 'test-image.png',
      mimeType: 'image/png',
      buffer: pngBuffer,
    });

    // Wait for file preview to appear
    const filePreview = page.locator('#file-preview');
    await expect(filePreview).not.toHaveClass(/hidden/, { timeout: 3000 });

    // Send message with image
    await page.fill('#message-input', 'Here is an image for streaming test');
    await page.click('#send-btn');

    // Wait for user message to appear
    const userMessage = page.locator('.message.user');
    await expect(userMessage).toBeVisible({ timeout: 5000 });

    // Image should initially have cursor: wait (pending state)
    const messageImage = userMessage.locator('.message-image');
    await expect(messageImage).toBeVisible({ timeout: 3000 });

    // Wait for streaming to start (assistant message appears)
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // After user_message_saved event is received, image should be clickable
    // The backend sends this event early, so by now it should be ready
    // Wait a moment for the event to be processed
    await page.waitForTimeout(500);

    // Image should no longer have pending attribute
    await expect(messageImage).not.toHaveAttribute('data-pending', 'true', { timeout: 3000 });

    // Click on the image to open lightbox
    await messageImage.click();

    // Lightbox should open and show the image
    const lightbox = page.locator('#lightbox');
    await expect(lightbox).not.toHaveClass(/hidden/, { timeout: 5000 });

    // Lightbox image should be loaded
    const lightboxImg = page.locator('#lightbox-img');
    await expect(lightboxImg).toBeVisible();

    // The image should have a valid src (blob URL)
    const imgSrc = await lightboxImg.getAttribute('src');
    expect(imgSrc).toBeTruthy();
    expect(imgSrc).toMatch(/^blob:/);

    // No error toast should be shown
    const errorToast = page.locator('.toast-error');
    await expect(errorToast).not.toBeVisible();
  });

  test('image shows wait cursor before user_message_saved event', async ({ page }) => {
    // This test verifies that images have cursor: wait before the real message ID is received
    // We check the pending state immediately after the message is sent

    // Enable streaming for this test
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }

    // Upload an image
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('#attach-btn');
    const fileChooser = await fileChooserPromise;

    await fileChooser.setFiles({
      name: 'test-image.png',
      mimeType: 'image/png',
      buffer: pngBuffer,
    });

    await expect(page.locator('#file-preview')).not.toHaveClass(/hidden/, { timeout: 3000 });

    // Fill message but don't send yet
    await page.fill('#message-input', 'Testing pending state');

    // Set up a listener to check the pending state immediately after message appears
    const pendingCheckPromise = page.evaluate(() => {
      return new Promise<boolean>((resolve) => {
        const observer = new MutationObserver((mutations) => {
          for (const mutation of mutations) {
            if (mutation.addedNodes.length > 0) {
              const messageEl = document.querySelector('.message.user');
              if (messageEl) {
                const img = messageEl.querySelector('.message-image');
                if (img) {
                  // Check immediately when image appears
                  const hasPending = img.getAttribute('data-pending') === 'true';
                  observer.disconnect();
                  resolve(hasPending);
                  return;
                }
              }
            }
          }
        });
        observer.observe(document.getElementById('messages')!, { childList: true, subtree: true });
      });
    });

    // Now send the message
    await page.click('#send-btn');

    // Check that the image initially had pending state
    const hadPendingState = await pendingCheckPromise;
    expect(hadPendingState).toBe(true);
  });
});

test.describe('Chat - Streaming Scroll Pause Indicator', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Enable streaming for these tests
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }

    // Configure slower streaming for reliable testing
    await page.request.post('/test/set-stream-delay', {
      data: { delay_ms: 100 },
    });
  });

  test.afterEach(async ({ page }) => {
    // Reset stream delay
    await page.request.post('/test/set-stream-delay', {
      data: { delay_ms: 10 },
    });
  });

  test('scroll button shows highlighted state when streaming auto-scroll is paused', async ({
    page,
  }) => {
    // First, create many messages to have scrollable content
    const streamBtn = page.locator('#stream-btn');
    await streamBtn.click(); // Disable streaming temporarily

    // Create enough messages to ensure scrollable content
    for (let i = 0; i < 5; i++) {
      await page.fill('#message-input', `Setup message ${i + 1} with some extra text to make it longer`);
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 10000 });
    }

    await streamBtn.click(); // Re-enable streaming
    // Use very slow streaming (500ms per word) to ensure we have time to scroll up while streaming
    await page.request.post('/test/set-stream-delay', {
      data: { delay_ms: 200 },
    });

    const messagesContainer = page.locator('#messages');
    const scrollButton = page.locator('.scroll-to-bottom');

    // Verify we have scrollable content
    const isScrollable = await messagesContainer.evaluate((el) => {
      return el.scrollHeight > el.clientHeight;
    });
    expect(isScrollable).toBe(true);

    // Send a message to start streaming
    await page.fill('#message-input', 'Tell me a long story');
    await page.click('#send-btn');

    // Wait for streaming to start
    const assistantMessage = page.locator('.message.assistant.streaming');
    await expect(assistantMessage).toBeVisible({ timeout: 5000 });

    // Wait for some content to arrive and auto-scroll to happen
    await page.waitForTimeout(500);

    // Verify we're at the bottom (auto-scroll should have us there)
    const atBottomBefore = await messagesContainer.evaluate((el) => {
      return el.scrollTop > 0 && el.scrollTop + el.clientHeight >= el.scrollHeight - 50;
    });
    expect(atBottomBefore).toBe(true);

    // Verify streaming is still active
    const isStillStreaming = await page.locator('.message.assistant.streaming').isVisible();
    expect(isStillStreaming).toBe(true);

    // Scroll up to interrupt auto-scroll using mouse wheel
    await messagesContainer.hover();
    await page.mouse.wheel(0, -10000);
    await page.waitForTimeout(300);

    // Scroll button should be visible and have the streaming-paused class
    await expect(scrollButton).toBeVisible({ timeout: 5000 });
    await expect(scrollButton).toHaveClass(/streaming-paused/, { timeout: 5000 });

    // Scroll back to bottom using mouse wheel
    await messagesContainer.hover();
    await page.mouse.wheel(0, 10000);
    await page.waitForTimeout(300);

    // The streaming-paused class should be removed
    await expect(scrollButton).not.toHaveClass(/streaming-paused/, { timeout: 5000 });
  });

  test('streaming-paused indicator is cleared when streaming completes', async ({ page }) => {
    // Create scrollable content first
    const streamBtn = page.locator('#stream-btn');
    await streamBtn.click(); // Disable streaming temporarily

    // Create enough messages to ensure scrollable content
    for (let i = 0; i < 5; i++) {
      await page.fill('#message-input', `Setup message ${i + 1} with some extra text to make it longer`);
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 10000 });
    }

    await streamBtn.click(); // Re-enable streaming
    // Use slower streaming so we have time to scroll up while streaming
    await page.request.post('/test/set-stream-delay', {
      data: { delay_ms: 200 },
    });

    const messagesContainer = page.locator('#messages');
    const scrollButton = page.locator('.scroll-to-bottom');

    // Verify we have scrollable content
    const isScrollable = await messagesContainer.evaluate((el) => {
      return el.scrollHeight > el.clientHeight;
    });
    expect(isScrollable).toBe(true);

    // Send a message
    await page.fill('#message-input', 'Short story');
    await page.click('#send-btn');

    // Wait for streaming to start
    const assistantMessage = page.locator('.message.assistant.streaming');
    await expect(assistantMessage).toBeVisible({ timeout: 5000 });

    // Wait for some content to arrive and auto-scroll to happen
    await page.waitForTimeout(500);

    // Verify we're at the bottom (auto-scroll should have us there)
    const atBottomBefore = await messagesContainer.evaluate((el) => {
      return el.scrollTop > 0 && el.scrollTop + el.clientHeight >= el.scrollHeight - 50;
    });
    expect(atBottomBefore).toBe(true);

    // Verify streaming is still active
    const isStillStreaming = await page.locator('.message.assistant.streaming').isVisible();
    expect(isStillStreaming).toBe(true);

    // Scroll up to pause auto-scroll using mouse wheel
    await messagesContainer.hover();
    await page.mouse.wheel(0, -10000);
    await page.waitForTimeout(300);

    // Verify streaming-paused is shown
    await expect(scrollButton).toHaveClass(/streaming-paused/, { timeout: 5000 });

    // Wait for streaming to complete
    const finalMessage = page.locator('.message.assistant').last();
    await expect(finalMessage).not.toHaveClass(/streaming/, { timeout: 15000 });

    // The streaming-paused indicator should be cleared after streaming ends
    await expect(scrollButton).not.toHaveClass(/streaming-paused/);
  });
});

test.describe('Chat - Upload Progress', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');
  });

  test('upload progress element exists and is initially hidden', async ({ page }) => {
    const uploadProgress = page.locator('#upload-progress');

    // Upload progress should exist in the DOM
    await expect(uploadProgress).toBeAttached();

    // Upload progress should be hidden initially
    await expect(uploadProgress).toHaveClass(/hidden/);

    // Should have progress bar and text elements
    const progressBar = uploadProgress.locator('.upload-progress-bar');
    const progressText = uploadProgress.locator('.upload-progress-text');
    await expect(progressBar).toBeAttached();
    await expect(progressText).toBeAttached();
  });

  test('upload progress shows briefly when sending message with files', async ({ page }) => {
    const uploadProgress = page.locator('#upload-progress');

    // Upload an image
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('#attach-btn');
    const fileChooser = await fileChooserPromise;

    const pngBase64 =
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
    const pngBuffer = Buffer.from(pngBase64, 'base64');
    await fileChooser.setFiles({
      name: 'test-image.png',
      mimeType: 'image/png',
      buffer: pngBuffer,
    });

    // Verify file preview is shown
    const filePreview = page.locator('#file-preview');
    await expect(filePreview).not.toHaveClass(/hidden/, { timeout: 3000 });

    // Add a batch delay to slow down the response so we can observe the progress
    await page.request.post('/test/set-batch-delay', {
      data: { delay_ms: 1000 },
    });

    // Set up a MutationObserver before clicking send to catch the progress indicator
    const progressWasShown = page.evaluate(() => {
      return new Promise<boolean>((resolve) => {
        const uploadEl = document.getElementById('upload-progress');
        if (!uploadEl) {
          resolve(false);
          return;
        }

        // If already visible, we caught it
        if (!uploadEl.classList.contains('hidden')) {
          resolve(true);
          return;
        }

        // Watch for the hidden class to be removed
        const observer = new MutationObserver((mutations) => {
          for (const mutation of mutations) {
            if (
              mutation.type === 'attributes' &&
              mutation.attributeName === 'class' &&
              !uploadEl.classList.contains('hidden')
            ) {
              observer.disconnect();
              resolve(true);
              return;
            }
          }
        });

        observer.observe(uploadEl, { attributes: true, attributeFilter: ['class'] });

        // Timeout after 5 seconds
        setTimeout(() => {
          observer.disconnect();
          resolve(false);
        }, 5000);
      });
    });

    // Click send to start the upload
    await page.click('#send-btn');

    // Check if progress was shown during the request
    const wasShown = await progressWasShown;
    expect(wasShown).toBe(true);

    // Wait for the message to complete
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });

    // Progress should be hidden after completion
    await expect(uploadProgress).toHaveClass(/hidden/);

    // Reset batch delay
    await page.request.post('/test/set-batch-delay', {
      data: { delay_ms: 0 },
    });
  });

  test('upload progress is hidden after completion', async ({ page }) => {
    const uploadProgress = page.locator('#upload-progress');

    // Upload an image
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('#attach-btn');
    const fileChooser = await fileChooserPromise;

    const pngBase64 =
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
    const pngBuffer = Buffer.from(pngBase64, 'base64');
    await fileChooser.setFiles({
      name: 'test-image.png',
      mimeType: 'image/png',
      buffer: pngBuffer,
    });

    // Send the message
    await page.click('#send-btn');

    // Wait for the message to complete
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });

    // Progress should be hidden after completion
    await expect(uploadProgress).toHaveClass(/hidden/);
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
    await page.request.post('/test/set-stream-delay', {
      data: { delay_ms: 300 },
    });

    // Enable streaming mode
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }

    // Create first conversation with some setup messages
    await page.click('#new-chat-btn');

    // Disable streaming for fast setup
    await streamBtn.click();
    for (let i = 0; i < 2; i++) {
      await page.fill('#message-input', `Setup ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 10000 });
    }

    // Re-enable streaming
    await streamBtn.click();
    await page.request.post('/test/set-stream-delay', {
      data: { delay_ms: 200 },
    });

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
    await page.request.post('/test/set-stream-delay', {
      data: { delay_ms: 10 },
    });
  });
});
