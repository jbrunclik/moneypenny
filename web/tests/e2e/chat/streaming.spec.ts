/**
 * E2E tests for streaming mode, auto-scroll, stop button, and scroll pause indicator
 */
import {
  test,
  expect,
  enableStreaming,
  disableStreaming,
  setStreamDelay,
  resetStreamDelay,
} from './fixtures';

test.describe('Chat - Streaming Mode', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Enable streaming
    await enableStreaming(page);
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

test.describe('Chat - Streaming Auto-Scroll', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Enable streaming for auto-scroll tests
    await enableStreaming(page);
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

  test('scroll position is maintained when scrolling up during active token streaming', async ({
    page,
  }) => {
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
      el.scrollTop = 0;
      el.dispatchEvent(new Event('scroll'));
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

  test('rapid scrolling during streaming does not cause flicker or unexpected scroll jumps', async ({
    page,
  }) => {
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

test.describe('Chat - Stop Streaming', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Enable streaming for stop tests
    await enableStreaming(page);

    // Set a very slow stream delay so there's time to click the stop button
    // Default is 10ms which is too fast for tests that need to interact with the stop button
    // With ~10 words in the response and 1000ms per word, we get ~10 seconds of streaming
    await setStreamDelay(page, 1000);
  });

  test.afterEach(async ({ page }) => {
    // Reset stream delay to default after each test
    await resetStreamDelay(page);
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
    await disableStreaming(page);

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

test.describe('Chat - Streaming Scroll Pause Indicator', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Enable streaming for these tests
    await enableStreaming(page);

    // Configure slower streaming for reliable testing
    await setStreamDelay(page, 100);
  });

  test.afterEach(async ({ page }) => {
    // Reset stream delay
    await resetStreamDelay(page);
  });

  test('scroll button shows highlighted state when streaming auto-scroll is paused', async ({
    page,
  }) => {
    // First, create many messages to have scrollable content
    const streamBtn = page.locator('#stream-btn');
    await streamBtn.click(); // Disable streaming temporarily

    // Create enough messages to ensure scrollable content
    for (let i = 0; i < 5; i++) {
      await page.fill(
        '#message-input',
        `Setup message ${i + 1} with some extra text to make it longer`
      );
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 10000 });
    }

    await streamBtn.click(); // Re-enable streaming
    // Use very slow streaming (500ms per word) to ensure we have time to scroll up while streaming
    await setStreamDelay(page, 200);

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
      await page.fill(
        '#message-input',
        `Setup message ${i + 1} with some extra text to make it longer`
      );
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 10000 });
    }

    await streamBtn.click(); // Re-enable streaming
    // Use slower streaming so we have time to scroll up while streaming
    await setStreamDelay(page, 200);

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
