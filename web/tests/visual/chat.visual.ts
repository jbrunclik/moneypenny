/**
 * Visual regression tests for chat interface
 */
import { test, expect } from '../global-setup';

test.describe('Visual: Chat Interface', () => {
  test('empty conversation state', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Wait for welcome message to appear
    await page.waitForSelector('.welcome-message');

    // Wait for any animations to complete
    await page.waitForTimeout(500);

    await expect(page).toHaveScreenshot('empty-conversation.png', {
      fullPage: true,
    });
  });

  test('conversation with messages', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Send a message
    await page.fill('#message-input', 'Hello, this is a test message!');
    await page.click('#send-btn');

    // Wait for response
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Wait for animations
    await page.waitForTimeout(500);

    await expect(page).toHaveScreenshot('conversation-with-messages.png', {
      fullPage: true,
    });
  });

  test('sidebar with conversations', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Create multiple conversations
    for (let i = 0; i < 3; i++) {
      await page.click('#new-chat-btn');
      await page.fill('#message-input', `Test message ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector('.message.assistant', { timeout: 10000 });
    }

    // Wait for animations
    await page.waitForTimeout(500);

    await expect(page.locator('#sidebar')).toHaveScreenshot('sidebar-conversations.png');
  });

  test('message input focused', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Focus on input
    await page.focus('#message-input');

    // Type some text
    await page.fill('#message-input', 'Typing a message...');

    await expect(page.locator('.input-container')).toHaveScreenshot('input-focused.png');
  });

  test('model selector dropdown', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Open model selector dropdown
    const modelSelectorBtn = page.locator('#model-selector-btn');
    await modelSelectorBtn.click();

    // Wait for dropdown to be visible
    await expect(page.locator('#model-dropdown')).not.toHaveClass(/hidden/);

    await expect(page.locator('.input-toolbar')).toHaveScreenshot('model-selector.png');
  });
});

test.describe('Visual: Long Content Wrapping', () => {
  test('long URL in user message wraps correctly', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Disable streaming for reliable mock responses
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }

    // Send a message with a very long URL
    const longUrl = 'https://www.example.com/very/long/path/that/should/wrap/properly/in/the/message/bubble/without/breaking/layout/file.pdf';
    await page.fill('#message-input', longUrl);
    await page.click('#send-btn');

    // Wait for response
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Wait for animations
    await page.waitForTimeout(500);

    // Screenshot the user message to verify URL wrapping
    const userMessage = page.locator('.message.user').first();
    await expect(userMessage).toHaveScreenshot('user-message-long-url.png');
  });

  test('short message displays correctly', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Disable streaming for reliable mock responses
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }

    // Send a short message
    await page.fill('#message-input', 'ahoj');
    await page.click('#send-btn');

    // Wait for response
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Wait for animations
    await page.waitForTimeout(500);

    // Screenshot the user message to verify it doesn't collapse
    const userMessage = page.locator('.message.user').first();
    await expect(userMessage).toHaveScreenshot('user-message-short.png');
  });
});

test.describe('Visual: Chat States', () => {
  // Note: Loading state test removed as it's inherently flaky - the mock responds too quickly
  // to reliably capture the loading state. Would require artificially slowing down the mock.

  test('stream button active', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Ensure streaming is enabled
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }

    await expect(streamBtn).toHaveScreenshot('stream-btn-active.png');
  });

  test('search button active', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Activate search
    const searchBtn = page.locator('#search-btn');
    await searchBtn.click();

    await expect(searchBtn).toHaveScreenshot('search-btn-active.png');
  });
});

test.describe('Visual: Thinking Indicator', () => {
  // Note: Visual tests for thinking indicator are run via E2E tests instead.
  // The thinking indicator only appears during streaming and is difficult to capture
  // in visual tests because:
  // 1. The mock server emits thinking events quickly, making capture timing-sensitive
  // 2. The indicator is removed after finalization if no meaningful content (by design)
  //
  // The E2E tests in chat.spec.ts verify the thinking indicator behavior.
  // The component structure and styling are covered by unit tests.

  test('message with streaming response', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Ensure streaming is enabled
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }

    // Send a message containing "think" to trigger thinking events
    await page.fill('#message-input', 'Please think about this question');
    await page.click('#send-btn');

    // Wait for streaming to complete
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toContainText('mock response', { timeout: 10000 });

    // Wait for animations to complete
    await page.waitForTimeout(500);

    // Screenshot the message (may or may not have thinking indicator based on timing)
    await expect(assistantMessage).toHaveScreenshot('message-with-streaming-response.png');
  });

  test('message with tool usage', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Ensure streaming is enabled
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed !== 'true') {
      await streamBtn.click();
    }

    // Enable search to trigger web_search tool
    const searchBtn = page.locator('#search-btn');
    await searchBtn.click();

    // Send a message
    await page.fill('#message-input', 'Search for something');
    await page.click('#send-btn');

    // Wait for streaming to complete
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toContainText('mock response', { timeout: 10000 });

    // Wait for animations
    await page.waitForTimeout(500);

    // Screenshot the message (may or may not have tool indicator based on timing)
    await expect(assistantMessage).toHaveScreenshot('message-with-tool-usage.png');
  });
});

test.describe('Visual: Sync UI', () => {
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

  test('unread badge on conversation', async ({ page }) => {
    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Create second conversation to switch to
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Inject unread badge via JS to simulate sync update
    // (since the mock server doesn't support multi-tab sync simulation)
    await page.evaluate(() => {
      const convItem = document.querySelector('.conversation-item-wrapper:not(.active) .conversation-item');
      if (convItem) {
        const badge = document.createElement('span');
        badge.className = 'unread-badge';
        badge.textContent = '3';
        convItem.appendChild(badge);
      }
    });

    // Wait for any animations
    await page.waitForTimeout(300);

    // Screenshot the sidebar showing unread badge
    await expect(page.locator('#sidebar')).toHaveScreenshot('sidebar-unread-badge.png');
  });

  test('unread badge with high count (99+)', async ({ page }) => {
    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Create second conversation to switch to
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Inject unread badge with 99+ count
    await page.evaluate(() => {
      const convItem = document.querySelector('.conversation-item-wrapper:not(.active) .conversation-item');
      if (convItem) {
        const badge = document.createElement('span');
        badge.className = 'unread-badge';
        badge.textContent = '99+';
        convItem.appendChild(badge);
      }
    });

    // Wait for any animations
    await page.waitForTimeout(300);

    // Screenshot just the conversation item with badge
    const convItem = page.locator('.conversation-item-wrapper:not(.active)').first();
    await expect(convItem).toHaveScreenshot('conversation-unread-99plus.png');
  });

  test('new messages available banner', async ({ page }) => {
    // Create a conversation with messages
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Inject the "New messages available" banner via JS
    await page.evaluate(() => {
      const messagesContainer = document.getElementById('messages');
      if (messagesContainer) {
        const banner = document.createElement('div');
        banner.className = 'new-messages-banner';
        banner.innerHTML = `
          <span>New messages available</span>
          <button class="btn btn-small">Reload</button>
        `;
        messagesContainer.insertBefore(banner, messagesContainer.firstChild);
      }
    });

    // Wait for any animations
    await page.waitForTimeout(300);

    // Screenshot the messages area with banner
    await expect(page.locator('#messages')).toHaveScreenshot('new-messages-banner.png');
  });
});
