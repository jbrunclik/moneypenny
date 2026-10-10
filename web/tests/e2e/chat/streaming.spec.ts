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
  setMockResponse,
  clearMockResponse,
  setEmitRetry,
  clickStop,
} from './fixtures';

test.describe('Chat - Streaming Mode', () => {
  test.beforeEach(async ({ page }) => {
    // Reset shared mock state up front so a custom response / stream delay left
    // by an earlier test can't leak in (tests that need custom values set them
    // after this).
    await clearMockResponse(page);
    await resetStreamDelay(page);

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

  test('shows a retry status while the model is retried, then clears it', async ({ page }) => {
    await setEmitRetry(page, 1500);
    try {
      // Record every retry status the page renders. WebKit sometimes hands a
      // small SSE chunk to the page only when the next one arrives (here: the
      // first token, 1.5s later), so the status can be rendered and cleared
      // in the same tick - asserting visibility during the hold was a flake.
      await page.evaluate(() => {
        const seen: string[] = [];
        (window as unknown as { __retryStatuses: string[] }).__retryStatuses = seen;
        new MutationObserver(() => {
          const el = document.querySelector('.message.assistant .streaming-retry-status');
          if (el?.textContent && !seen.includes(el.textContent)) seen.push(el.textContent);
        }).observe(document.body, { childList: true, subtree: true, characterData: true });
      });
      await page.fill('#message-input', 'Hello retry');
      await page.click('#send-btn');

      // Once tokens flow the status disappears
      await expect(page.locator('.message.assistant')).toContainText('Hello retry', {
        timeout: 20000,
      });
      await expect(page.locator('.message.assistant .streaming-retry-status')).toHaveCount(0);
      const statuses = await page.evaluate(
        () => (window as unknown as { __retryStatuses: string[] }).__retryStatuses
      );
      expect(statuses).toEqual([expect.stringContaining('retrying (attempt 1 of 3)')]);
    } finally {
      await setEmitRetry(page, 0);
    }
  });

  test('streams response tokens progressively via SSE', async ({ page }) => {
    await page.fill('#message-input', 'Hello streaming');
    await page.click('#send-btn');

    // Wait for assistant message to appear (streaming creates element immediately)
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 20000 });

    // Wait for streaming to complete - content should contain mock response
    // The mock streams "This is a mock response to: Hello streaming" word by word
    await expect(assistantMessage).toContainText('mock response', { timeout: 20000 });
    await expect(assistantMessage).toContainText('Hello streaming', { timeout: 20000 });
  });

  test('shows both user and assistant messages after streaming', async ({ page }) => {
    await page.fill('#message-input', 'Stream test');
    await page.click('#send-btn');

    // Wait for streaming to complete
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toContainText('mock response', { timeout: 20000 });

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
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 20000 });
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
    // Let the send-to-top glide finish: it only aborts on a move of more than
    // a few px, and its target here sits ~5px from the top
    await page.waitForTimeout(700);

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
    await expect(assistantMessage).toContainText('mock response', { timeout: 20000 });

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
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 20000 });
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
    await expect(assistantMessage).toContainText('mock response', { timeout: 20000 });

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
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 20000 });
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
    await expect(assistantMessage).toContainText('mock response', { timeout: 20000 });

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
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 20000 });
    }
    await streamBtn.click(); // Re-enable streaming

    const messagesContainer = page.locator('#messages');

    // Send a message to start streaming
    await page.fill('#message-input', 'Tell me a story');
    await page.click('#send-btn');

    // Wait for streaming to start
    const assistantMessage = page.locator('.message.assistant').last();
    await expect(assistantMessage).toBeVisible({ timeout: 5000 });
    // Let the send-to-top glide finish: it aborts only on a real move, and a
    // "scroll to 0" from a start already near 0 isn't one (WebKit under load)
    await page.waitForTimeout(700);

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
      const scrollTop = await messagesContainer.evaluate((el) => el.scrollTop);
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
    await expect(assistantMessage).toContainText('mock response', { timeout: 20000 });

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

test.describe('Chat - Mid-run Steering', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');
    await enableStreaming(page);
  });

  test('sending while streaming interjects instead of blocking', async ({ page, request }) => {
    // Slow the stream so the turn is reliably still running when we steer
    await request.post('/test/set-stream-delay', { data: { delay_ms: 150 } });

    await page.fill('#message-input', 'First question - long response please');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant.streaming', { timeout: 10000 });

    // Send steering text mid-stream: must POST to the interject route
    const interjectRequest = page.waitForRequest(
      (req) => req.url().includes('/chat/interject') && req.method() === 'POST',
      { timeout: 10000 }
    );
    await page.fill('#message-input', 'Actually focus on the 2025 season');
    await page.click('#send-btn');
    await interjectRequest;

    // The steering text renders as a user bubble immediately
    await expect(
      page.locator('.message.user', { hasText: 'Actually focus on the 2025 season' })
    ).toBeVisible();

    // The original turn keeps streaming to completion
    await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 20000 });

    // The reply takes the steering into account, so it reads AFTER it - and
    // stays the latest assistant turn (regenerate/continue), live and after
    // a reload. (Below the steering bubble it ended the turn on a user
    // message and lost both actions.)
    const order = (): Promise<string[]> =>
      page.evaluate(() =>
        [...document.querySelectorAll('#messages .message')].map((el) =>
          el.classList.contains('user') ? 'user' : 'assistant'
        )
      );
    expect(await order()).toEqual(['user', 'user', 'assistant']);
    await expect(page.locator('.message.assistant.message--latest-assistant')).toHaveCount(1);

    // The steering message survives a reload (persisted server-side)
    await page.reload();
    await expect(
      page.locator('.message.user', { hasText: 'Actually focus on the 2025 season' })
    ).toBeVisible({ timeout: 10000 });
    expect(await order()).toEqual(['user', 'user', 'assistant']);
    await expect(page.locator('.message.assistant.message--latest-assistant')).toHaveCount(1);
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

    // Wait for streaming to complete naturally by waiting for the button to revert.
    // The mock streams one word per second (set in beforeEach) and the reply is
    // 12 words, so the nominal stream is ~12s: 15s left no margin on a loaded
    // CI runner (the last webkit retry in the suite). Give it 2.5x.
    // Note: We wait for btn-send class instead of text because the response text
    // ("mock response") appears early in the stream, before it's complete
    await expect(sendBtn).toHaveClass(/btn-send/, { timeout: 30000 });
    await expect(sendBtn).not.toHaveClass(/btn-stop/);
    await expect(sendBtn).toHaveAttribute('title', 'Send message');
  });

  test('stop keeps the partial reply with a Stopped note', async ({ page }) => {
    await page.fill('#message-input', 'Tell me a very long story please');
    await page.click('#send-btn');
    const assistant = page.locator('.message.assistant');
    await expect(assistant).toBeVisible({ timeout: 5000 });
    // Wait for real streamed text (the mock echoes the prompt), not the
    // loading placeholder: Stop before the server acked the turn is a plain abort
    await expect(assistant.locator('.message-content')).toContainText('Tell me', { timeout: 10000 });

    await clickStop(page);

    await expect(page.locator('.toast-info')).toContainText('Response stopped');
    const note = assistant.locator('.message-stopped-early');
    await expect(note).toContainText('Stopped.', { timeout: 5000 });
    await expect(note.locator('.message-stopped-early-continue')).toBeVisible();
    await expect(page.locator('#send-btn')).toHaveClass(/btn-send/);

    const partial = await assistant.locator('.message-content').innerText();
    await page.reload();
    const reloaded = page.locator('.message.assistant');
    await expect(reloaded.locator('.message-stopped-early')).toContainText('Stopped.');
    await expect(reloaded.locator('.message-content')).toHaveText(partial);
  });

  test('Stop shows a disabled Stopping state until the turn ends', async ({ page }) => {
    // Slow words widen the window between the click and the next server checkpoint
    await setStreamDelay(page, 3000);
    await page.fill('#message-input', 'Tell me a very long story please');
    await page.click('#send-btn');
    const assistant = page.locator('.message.assistant');
    // Real streamed text (the mock reply's first words), not the loading placeholder
    await expect(assistant.locator('.message-content')).toContainText('This is', { timeout: 10000 });

    const sendBtn = page.locator('#send-btn');
    await clickStop(page);

    await expect(sendBtn).toHaveAttribute('title', 'Stopping…');
    await expect(sendBtn).toBeDisabled();
    await expect(assistant.locator('.message-stopped-early')).toContainText('Stopped.', { timeout: 10000 });
    await expect(sendBtn).toHaveClass(/btn-send/);
    await expect(sendBtn).toHaveAttribute('title', 'Send message');
  });

  test('Continue after Stop streams the rest of the answer', async ({ page }) => {
    await page.fill('#message-input', 'Tell me a very long story please');
    await page.click('#send-btn');
    const assistant = page.locator('.message.assistant');
    await expect(assistant.locator('.message-content')).toContainText('Tell me', { timeout: 10000 });
    await clickStop(page);
    await expect(assistant.locator('.message-stopped-early')).toContainText('Stopped.', { timeout: 5000 });

    await setStreamDelay(page, 10);
    await setMockResponse(page, 'and the rest of the story');
    await assistant.locator('.message-stopped-early-continue').click();

    await expect(page.locator('.message.assistant')).toHaveCount(2, { timeout: 20000 });
    await expect(page.locator('.message.assistant').last()).toContainText('and the rest of the story');
    await expect(page.locator('.message.user')).toHaveCount(1);
    await clearMockResponse(page);
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
    await expect(assistantMessage).toBeVisible({ timeout: 20000 });

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

  test('stop during the thinking phase keeps the turn with a Stopped note', async ({ page }) => {
    await page.fill('#message-input', 'Let me think about this');
    await page.click('#send-btn');

    // The thinking event arrives only after the server acked the turn
    // (user_message_saved), so Stop here is a server-side stop
    const assistant = page.locator('.message.assistant');
    await expect(assistant).toContainText('Let me think about this...', { timeout: 10000 });

    await clickStop(page);

    await expect(page.locator('.toast-info')).toContainText('Response stopped');
    await expect(assistant.locator('.message-stopped-early')).toContainText('Stopped.', { timeout: 5000 });
    await expect(page.locator('#send-btn')).toHaveClass(/btn-send/);

    // Whatever was produced before the Stop landed (nothing, or the first
    // words) is what was saved: a reload shows the same reply
    // (the live turn's collapsed thinking summary is not part of the saved
    // reply - a reloaded message has no trace)
    const replyText = (content: import('@playwright/test').Locator) =>
      content.evaluate((el) => {
        const copy = el.cloneNode(true) as HTMLElement;
        copy.querySelector('.thinking-indicator')?.remove();
        return (copy.textContent ?? '').trim();
      });
    const live = await replyText(assistant.locator('.message-content'));
    await page.reload();
    const reloaded = page.locator('.message.assistant');
    await expect(reloaded.locator('.message-stopped-early')).toContainText('Stopped.', { timeout: 10000 });
    expect(await replyText(reloaded.locator('.message-content'))).toBe(live);
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
        // Long enough that a handful of messages overflow the tall (1024px)
        // E2E viewport even with the compact message density - the list must
        // be scrollable for this test's premise to hold.
        `Setup message ${i + 1}. ` +
          'This is a longer line of text to build up vertical height. '.repeat(12)
      );
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 20000 });
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

    // Scroll up to interrupt auto-scroll using wheel event (the scroll listener uses wheel/touchmove events)
    await messagesContainer.evaluate((el) => {
      // Dispatch wheel event first to trigger pause detection
      el.dispatchEvent(new WheelEvent('wheel', { deltaY: -100 }));
      // Then set scrollTop to actually scroll
      el.scrollTop = 0;
    });

    // Scroll button should be visible and have the streaming-paused class
    await expect(scrollButton).toBeVisible({ timeout: 5000 });
    await expect(scrollButton).toHaveClass(/streaming-paused/, { timeout: 5000 });

    // Scroll back to bottom using JavaScript
    await messagesContainer.evaluate((el) => {
      el.scrollTop = el.scrollHeight;
      el.dispatchEvent(new Event('scroll'));
    });

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
        // Long enough that a handful of messages overflow the tall (1024px)
        // E2E viewport even with the compact message density - the list must
        // be scrollable for this test's premise to hold.
        `Setup message ${i + 1}. ` +
          'This is a longer line of text to build up vertical height. '.repeat(12)
      );
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 20000 });
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

    // Scroll up to pause auto-scroll using wheel event (the scroll listener uses wheel/touchmove events)
    await messagesContainer.evaluate((el) => {
      // Dispatch wheel event first to trigger pause detection
      el.dispatchEvent(new WheelEvent('wheel', { deltaY: -100 }));
      // Then set scrollTop to actually scroll
      el.scrollTop = 0;
    });

    // Verify streaming-paused is shown
    await expect(scrollButton).toHaveClass(/streaming-paused/, { timeout: 5000 });

    // Wait for streaming to complete
    const finalMessage = page.locator('.message.assistant').last();
    await expect(finalMessage).not.toHaveClass(/streaming/, { timeout: 15000 });

    // The streaming-paused indicator should be cleared after streaming ends
    await expect(scrollButton).not.toHaveClass(/streaming-paused/);
  });
});

/** Gap between the floating header's bottom edge and the latest user message's top. */
async function turnTopBelowHeader(
  page: import('@playwright/test').Page,
  headerSelector: string
): Promise<number> {
  return page.evaluate((sel) => {
    const header = document.querySelector<HTMLElement>(sel)!;
    const turns = document.querySelectorAll<HTMLElement>('.message.user');
    const turn = turns[turns.length - 1];
    return turn.getBoundingClientRect().top - header.getBoundingClientRect().bottom;
  }, headerSelector);
}

/** Empty space left under the last message (the reserved turn space). */
async function blankBelowLastMessage(page: import('@playwright/test').Page): Promise<number> {
  return page.evaluate(() => {
    const c = document.getElementById('messages')!;
    const last = [...c.querySelectorAll<HTMLElement>('.message')].pop()!;
    // A reservation still held is blank by definition (the message's wrapper
    // stretches to its min-height, so its bottom alone can't tell)
    if (c.querySelector('[data-turn-space]')) return Number.POSITIVE_INFINITY;
    const bottom = last.getBoundingClientRect().bottom - c.getBoundingClientRect().top + c.scrollTop;
    // The composer clearance: the ::after spacer plus the list gap before it
    const spacer = parseFloat(getComputedStyle(c, '::after').height) || 0;
    const clearance = spacer + (spacer > 0 ? parseFloat(getComputedStyle(c).rowGap) || 0 : 0);
    const listEnd = c.scrollHeight - parseFloat(getComputedStyle(c).paddingBottom) - clearance;
    return Math.round(listEnd - bottom);
  });
}

async function messagesScrollTop(page: import('@playwright/test').Page): Promise<number> {
  return page.evaluate(() => document.getElementById('messages')!.scrollTop);
}

const LONG_RESPONSE = Array.from(
  { length: 120 },
  (_, i) => `Line ${i + 1} of a long answer.`
).join('\n\n');

// Send-to-top (ChatGPT / Claude.ai): a new turn scrolls up so the user's
// message sits just under the floating header, the reply grows below it and
// the view does NOT chase it down - no jump when it finishes either. The
// header floats over the list, so "under the header" must clear it, not sit
// at the list's top edge (the first line used to hide under it).
test.describe('Chat - Send-to-top', () => {
  test.afterEach(async ({ page }) => {
    await clearMockResponse(page);
    await resetStreamDelay(page);
  });

  for (const layout of [
    { name: 'desktop', viewport: { width: 1280, height: 520 }, header: '.chat-header' },
    { name: 'phone', viewport: { width: 390, height: 664 }, header: '.mobile-header' },
  ]) {
    test.describe(layout.name, () => {
      test.use({ viewport: layout.viewport });

      test.beforeEach(async ({ page }) => {
        await clearMockResponse(page);
        await page.goto('/');
        if (layout.name === 'phone') {
          await page.waitForSelector('#menu-btn');
          await page.click('#menu-btn');
        }
        await page.click('#new-chat-btn');
        await enableStreaming(page);
      });

      test('a long reply streams below the message without moving the view', async ({ page }) => {
        // A first turn so the second has history to scroll past
        await setMockResponse(page, LONG_RESPONSE);
        await page.fill('#message-input', 'First question');
        await page.click('#send-btn');
        await expect(page.locator('.message.assistant').last()).not.toHaveClass(/streaming/, { timeout: 20000 });

        await page.fill('#message-input', 'Tell me everything');
        await page.click('#send-btn');
        const reply = page.locator('.message.assistant').last();
        await expect(reply).toContainText('Line 3', { timeout: 10000 });

        // The new message glides to the top, clear of the header
        await expect
          .poll(async () => {
            const gap = await turnTopBelowHeader(page, layout.header);
            return gap >= 0 && gap < 40;
          }, { timeout: 5000 })
          .toBe(true);
        await page.waitForTimeout(700); // the glide's last frames
        const anchored = await messagesScrollTop(page);

        // The reply outgrows the screen: the view stays, the pill offers the rest
        await expect(page.locator('.scroll-to-bottom.streaming-paused')).toBeVisible({ timeout: 10000 });
        expect(Math.abs((await messagesScrollTop(page)) - anchored)).toBeLessThan(2);

        // ...and nothing moves when it finishes
        await expect(reply).not.toHaveClass(/streaming/, { timeout: 20000 });
        await page.waitForTimeout(300);
        expect(Math.abs((await messagesScrollTop(page)) - anchored)).toBeLessThan(2);
        expect(await turnTopBelowHeader(page, layout.header)).toBeGreaterThanOrEqual(0);
        await expect(page.locator('.scroll-to-bottom')).toBeVisible();
      });

      test('a short reply streams under the message at the top, then settles without empty space', async ({
        page,
      }) => {
        // A later turn in an existing chat (the first turn re-renders the list)
        await setMockResponse(page, 'First answer.');
        await page.fill('#message-input', 'First question');
        await page.click('#send-btn');
        await expect(page.locator('.message.assistant')).not.toHaveClass(/streaming/, { timeout: 10000 });

        // Still streaming when the "at the top" check runs, even on a slow CI
        // runner (~5s of tokens) - a reply done before it settles to the bottom
        await setStreamDelay(page, 250);
        await setMockResponse(page, Array.from({ length: 20 }, (_, i) => `w${i}`).join(' '));
        await page.fill('#message-input', 'Quick question');
        await page.click('#send-btn');
        const reply = page.locator('.message.assistant').last();
        await expect(reply).toContainText('w0', { timeout: 10000 });

        // While it streams: the message glides to the top, room reserved below
        await expect
          .poll(async () => {
            const gap = await turnTopBelowHeader(page, layout.header);
            return gap >= 0 && gap < 40;
          }, { timeout: 5000 })
          .toBe(true);

        // Done: the reservation is released - no empty area left behind
        await expect(reply).not.toHaveClass(/streaming/, { timeout: 15000 });
        await expect.poll(() => blankBelowLastMessage(page), { timeout: 3000 }).toBeLessThan(40);
        await expect(reply).toBeInViewport();
        await expect(page.locator('.message.user').last()).toBeInViewport();
        await expect(page.locator('.scroll-to-bottom')).toBeHidden();
      });

      test('scrolling to the bottom mid-stream follows the reply again', async ({ page }) => {
        await setMockResponse(page, LONG_RESPONSE);
        await page.fill('#message-input', 'Tell me everything');
        await page.click('#send-btn');
        const pill = page.locator('.scroll-to-bottom.streaming-paused');
        await expect(pill).toBeVisible({ timeout: 10000 });

        await pill.click();
        // Following: the view keeps up with the growing reply
        await expect
          .poll(
            () =>
              page.evaluate(() => {
                const c = document.getElementById('messages')!;
                return c.scrollHeight - c.scrollTop - c.clientHeight;
              }),
            { timeout: 5000 }
          )
          .toBeLessThan(50);
        const before = await messagesScrollTop(page);
        await expect.poll(() => messagesScrollTop(page), { timeout: 5000 }).toBeGreaterThan(before + 50);
      });

      for (const reply of [
        { name: 'long', text: LONG_RESPONSE, last: 'Line 120' },
        // A short reply in a new chat: the loader's reserved space moves to
        // the reply, and the post-turn compaction refresh used to pin the
        // "at bottom" anchored view, hiding the message under the header
        { name: 'short', text: 'Short and sweet.', last: 'Short and sweet.' },
      ]) {
        test(`a ${reply.name} batch reply lands below the message at the top`, async ({ page }) => {
          // The phone hides the toolbar holding the toggle - press it directly
          await page.evaluate(() => document.getElementById('stream-btn')!.click());
          await expect(page.locator('#stream-btn')).toHaveAttribute('aria-pressed', 'false');
          // A later turn in an existing chat (the first turn re-renders the list)
          await setMockResponse(page, 'First answer.');
          await page.fill('#message-input', 'First question');
          await page.click('#send-btn');
          await expect(page.locator('.message.assistant')).toContainText('First answer', { timeout: 10000 });
          await setMockResponse(page, reply.text);
          await page.fill('#message-input', 'Tell me everything');
          await page.click('#send-btn');
          await expect(page.locator('.message.assistant').last()).toContainText(reply.last, { timeout: 20000 });
          await page.waitForTimeout(800);

          if (reply.name === 'long') {
            const gap = await turnTopBelowHeader(page, layout.header);
            expect(gap).toBeGreaterThanOrEqual(0);
            expect(gap).toBeLessThan(40);
          } else {
            // A short reply releases the reserved space: no empty area, both visible
            await expect.poll(() => blankBelowLastMessage(page), { timeout: 3000 }).toBeLessThan(40);
            await expect(page.locator('.message.user').last()).toBeInViewport();
          }
        });
      }
    });
  }
});

// Every way a turn can end must give back its reserved space - not only a
// normal done. A stop, an error or a dropped bubble left the "empty space"
// (and the bottom-align switched off) until the next message.
test.describe('Send-to-top - reserved space after an abnormal end', () => {
  test.use({ viewport: { width: 390, height: 664 } });

  test.afterEach(async ({ page }) => {
    await page.request.post('/test/set-emit-thinking', { data: { emit: false } });
    await clearMockResponse(page);
    await resetStreamDelay(page);
  });

  test('stopping during the thinking phase leaves no empty space', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#menu-btn');
    await page.click('#menu-btn');
    await page.click('#new-chat-btn');
    await enableStreaming(page);
    await setMockResponse(page, 'First answer.');
    await page.fill('#message-input', 'First question');
    await page.click('#send-btn');
    await expect(page.locator('.message.assistant')).not.toHaveClass(/streaming/, { timeout: 10000 });

    await page.request.post('/test/set-emit-thinking', { data: { emit: true, text: 'Pondering...', hold_ms: 5000 } });
    await page.fill('#message-input', 'Second question');
    await page.click('#send-btn');
    await expect(page.locator('.message.assistant.streaming')).toBeVisible();
    await page.waitForTimeout(800);
    await clickStop(page);
    await expect(page.locator('.message.assistant.streaming')).toHaveCount(0, { timeout: 15000 });

    await expect.poll(() => blankBelowLastMessage(page), { timeout: 3000 }).toBeLessThan(40);
    expect(await page.evaluate(() => document.getElementById('messages')!.classList.contains('turn-anchored'))).toBe(false);
  });
});

// The user touching the list takes over from any smooth scroll of ours:
// the glide only aborted on a >5px deviation, so a press-and-hold (or a drag
// along with it) was fought for up to 600ms.
test.describe('Send-to-top - the user takes over the glide', () => {
  test.use({ viewport: { width: 390, height: 664 }, hasTouch: true });

  test('a touch mid-glide stops it where it is', async ({ page, request }) => {
    const messages = Array.from({ length: 30 }, (_, i) => ({
      role: i % 2 ? 'assistant' : 'user',
      content: `Message ${i + 1} ` + 'lorem ipsum '.repeat(20),
    }));
    await request.post('/test/seed', { data: { conversations: [{ title: 'History', messages }] } });
    await page.goto('/');
    await page.click('#menu-btn');
    await page.locator('.conversation-item-wrapper', { hasText: 'History' }).click();
    await page.waitForTimeout(800);
    await enableStreaming(page);
    // Reading further up: the send pins to the bottom first, then glides
    await page.evaluate(() => {
      document.getElementById('messages')!.scrollTop = 0;
    });

    // Still streaming throughout (a finished reply releases its space)
    await setMockResponse(page, LONG_RESPONSE);
    await setStreamDelay(page, 150);
    await page.fill('#message-input', 'New question');
    await page.click('#send-btn');
    // The glide starts with the reply bubble; catch it mid-flight
    await page.waitForSelector('.message.assistant.streaming');
    await page.waitForTimeout(80);
    await page.evaluate(() => {
      const c = document.getElementById('messages')!;
      c.dispatchEvent(new Event('touchstart', { bubbles: true }));
    });
    const held = await page.evaluate(() => document.getElementById('messages')!.scrollTop);
    await page.waitForTimeout(700);

    const after = await page.evaluate(() => document.getElementById('messages')!.scrollTop);
    expect(Math.abs(after - held)).toBeLessThan(2);
    await clearMockResponse(page);
    await resetStreamDelay(page);
  });
});

// The band between header and composer changing mid-turn (iOS keyboard,
// a growing composer) must keep the anchored turn where it is.
test.describe('Send-to-top - band changes keep the turn anchored', () => {
  test.use({ viewport: { width: 390, height: 664 } });

  test.afterEach(async ({ page }) => {
    await clearMockResponse(page);
    await resetStreamDelay(page);
  });

  test('typing a multi-line follow-up mid-stream keeps the turn under the header', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#menu-btn');
    await page.click('#menu-btn');
    await page.click('#new-chat-btn');
    await enableStreaming(page);
    await setMockResponse(page, 'First answer.');
    await page.fill('#message-input', 'First question');
    await page.click('#send-btn');
    await expect(page.locator('.message.assistant')).not.toHaveClass(/streaming/, { timeout: 10000 });

    await setMockResponse(page, LONG_RESPONSE);
    await setStreamDelay(page, 150);
    await page.fill('#message-input', 'Tell me everything');
    await page.click('#send-btn');
    await expect
      .poll(async () => {
        const gap = await turnTopBelowHeader(page, '.mobile-header');
        return gap >= 0 && gap < 40;
      }, { timeout: 5000 })
      .toBe(true);
    await page.waitForTimeout(700);
    const anchored = await turnTopBelowHeader(page, '.mobile-header');

    // The composer grows by several lines
    await page.fill('#message-input', 'One\nTwo\nThree\nFour\nFive');
    await page.waitForTimeout(600);

    expect(Math.abs((await turnTopBelowHeader(page, '.mobile-header')) - anchored)).toBeLessThan(3);
  });
});

// While the reply is still only thinking / using tools, the trace growing
// past the screen is not "new messages" - the pill waits for answer text.
test.describe('Send-to-top - no pill while thinking', () => {
  test.use({ viewport: { width: 390, height: 664 } });

  test.afterEach(async ({ page }) => {
    await page.request.post('/test/set-emit-thinking', { data: { emit: false } });
  });

  test('a long thinking trace does not raise the New messages pill', async ({ page }) => {
    const thoughts = Array.from({ length: 80 }, (_, i) => `Thought ${i + 1} about the joke.`).join('\n\n');
    await page.request.post('/test/set-emit-thinking', { data: { emit: true, text: thoughts, hold_ms: 4000 } });
    await page.goto('/');
    await page.waitForSelector('#menu-btn');
    await page.click('#menu-btn');
    await page.click('#new-chat-btn');
    await enableStreaming(page);

    await setMockResponse(page, Array.from({ length: 40 }, (_, i) => `Answer line ${i + 1}.`).join('\n\n'));
    await page.fill('#message-input', 'Was my joke funny?');
    await page.click('#send-btn');
    // Mid-thinking: the trace is far taller than the screen
    await page.waitForTimeout(2000);
    await expect(page.locator('.message.assistant')).toHaveClass(/streaming/);
    // One-shot, not toHaveCount (it retries until the stream ends and clears it)
    expect(await page.locator('.scroll-to-bottom.streaming-paused').count()).toBe(0);
    await clearMockResponse(page);
  });
});

// A program's auto-start turn (sports/language) answers a trigger chip, not
// a user bubble, and its quick-actions bar grows the composer after the
// reservation: the turn must end visible, without empty space.
test.describe('Send-to-top - program auto-start on a phone', () => {
  test.use({ viewport: { width: 375, height: 667 } });

  test('the session-start turn ends fully visible, without empty space', async ({ page }) => {
    await page.request.post('/test/set-sports-programs', {
      data: { programs: [{ id: 'pushups', name: 'Push-ups', emoji: '💪', created_at: '2026-01-01T00:00:00Z' }] },
    });
    await page.goto('/#/sports/pushups');
    await expect(page.locator('.message.assistant')).not.toHaveClass(/streaming/, { timeout: 15000 });

    // The reply released its reserved space and settled like a normal chat:
    // no empty area under it, the reply on screen
    await expect.poll(() => blankBelowLastMessage(page), { timeout: 3000 }).toBeLessThan(40);
    expect(await blankBelowLastMessage(page)).toBeGreaterThan(-40);
    await expect(page.locator('.message.assistant')).toBeInViewport();
  });

});

test.describe('Chat - Stop Streaming on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('stop keeps the partial reply with a Stopped note', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#menu-btn');
    // Below the mobile breakpoint new-chat lives in the sidebar
    await page.click('#menu-btn');
    await page.click('#new-chat-btn');
    await enableStreaming(page);
    await setStreamDelay(page, 1000);

    await page.fill('#message-input', 'Tell me a very long story please');
    await page.click('#send-btn');
    const assistant = page.locator('.message.assistant');
    await expect(assistant.locator('.message-content')).toContainText('Tell me', { timeout: 10000 });

    await clickStop(page);

    const note = assistant.locator('.message-stopped-early');
    await expect(note).toContainText('Stopped.', { timeout: 5000 });
    await expect(note.locator('.message-stopped-early-continue')).toBeVisible();
    await resetStreamDelay(page);
  });
});
