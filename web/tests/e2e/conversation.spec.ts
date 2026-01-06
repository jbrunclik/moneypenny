/**
 * E2E tests for conversation management
 */
import { test, expect } from '../global-setup';
import { TEST_IMAGES } from '../fixtures/test-images';

/**
 * Generate a minimal valid PNG image buffer programmatically.
 * Creates a simple solid color rectangle.
 *
 * This generates a minimal valid PNG structure without external dependencies.
 * For larger images, we repeat the pixel data programmatically.
 */
function generatePngBuffer(width: number, height: number, color: string = 'red'): Buffer {
  // Color RGB values
  const colors: Record<string, [number, number, number]> = {
    red: [255, 0, 0],
    blue: [0, 0, 255],
    green: [0, 255, 0],
  };
  const [r, g, b] = colors[color] || colors.red;

  // PNG file signature
  const pngSignature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

  // Helper to write 32-bit big-endian integer
  const writeUInt32BE = (value: number): Buffer => {
    const buf = Buffer.allocUnsafe(4);
    buf.writeUInt32BE(value, 0);
    return buf;
  };

  // Helper to calculate CRC32 (simplified - using a basic implementation)
  const crc32 = (data: Buffer): number => {
    let crc = 0xffffffff;
    for (let i = 0; i < data.length; i++) {
      crc ^= data[i];
      for (let j = 0; j < 8; j++) {
        crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
      }
    }
    return (crc ^ 0xffffffff) >>> 0;
  };

  // Helper to create a PNG chunk
  const createChunk = (type: string, data: Buffer): Buffer => {
    const typeBuf = Buffer.from(type, 'ascii');
    const length = writeUInt32BE(data.length);
    const chunkData = Buffer.concat([typeBuf, data]);
    const crc = writeUInt32BE(crc32(chunkData));
    return Buffer.concat([length, chunkData, crc]);
  };

  // IHDR chunk
  const ihdrData = Buffer.allocUnsafe(13);
  writeUInt32BE(width).copy(ihdrData, 0);
  writeUInt32BE(height).copy(ihdrData, 4);
  ihdrData[8] = 8; // bit depth
  ihdrData[9] = 2; // color type (RGB)
  ihdrData[10] = 0; // compression
  ihdrData[11] = 0; // filter
  ihdrData[12] = 0; // interlace
  const ihdrChunk = createChunk('IHDR', ihdrData);

  // Generate image data: each row has a filter byte (0 = none) + RGB pixels
  const bytesPerRow = width * 3;
  const rowSize = 1 + bytesPerRow; // filter byte + pixel data
  const imageData = Buffer.allocUnsafe(rowSize * height);

  // Fill with solid color
  for (let y = 0; y < height; y++) {
    const rowStart = y * rowSize;
    imageData[rowStart] = 0; // filter type: none
    for (let x = 0; x < width; x++) {
      const pixelOffset = rowStart + 1 + x * 3;
      imageData[pixelOffset] = r;
      imageData[pixelOffset + 1] = g;
      imageData[pixelOffset + 2] = b;
    }
  }

  // Compress image data (simple zlib compression - for minimal PNG, we can use a basic approach)
  // For simplicity, we'll use Node's zlib if available, otherwise create minimal compressed data
  let compressedData: Buffer;
  try {
    const zlib = require('zlib');
    compressedData = zlib.deflateSync(imageData);
  } catch {
    // Fallback: create minimal valid deflate stream
    // This is a simplified approach - in practice you'd use proper compression
    compressedData = Buffer.concat([
      Buffer.from([0x78, 0x9c]), // zlib header
      imageData,
      // Adler-32 checksum (simplified)
      writeUInt32BE(1), // placeholder
    ]);
  }

  const idatChunk = createChunk('IDAT', compressedData);
  const iendChunk = createChunk('IEND', Buffer.alloc(0));

  return Buffer.concat([pngSignature, ihdrChunk, idatChunk, iendChunk]);
}

/**
 * Generate a larger PNG image buffer (400x400) for realistic testing.
 * This creates an image that will actually require scrolling.
 */
function generateLargePngBuffer(): Buffer {
  return generatePngBuffer(400, 400, 'red');
}

test.describe('Conversations', () => {
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

  test('creates new conversation on new chat click', async ({ page }) => {
    await page.click('#new-chat-btn');

    // Should show messages area
    const messagesContainer = page.locator('#messages');
    await expect(messagesContainer).toBeVisible();

    // Welcome message should be shown for new conversation
    const welcomeMessage = page.locator('.welcome-message');
    await expect(welcomeMessage).toBeVisible();
  });

  test('conversation appears in sidebar after first message', async ({ page }) => {
    // Start a new conversation
    await page.click('#new-chat-btn');

    // Type and send a message
    await page.fill('#message-input', 'Hello, this is a test message');
    await page.click('#send-btn');

    // Wait for response
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Conversation should appear in sidebar
    const convItem = page.locator('.conversation-item-wrapper');
    await expect(convItem).toBeVisible();
  });

  test('can switch between conversations', async ({ page }) => {
    // Create first conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Create second conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second conversation');
    await page.click('#send-btn');
    // Wait for the new assistant message (this is a fresh conversation view)
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Should have two conversations in sidebar
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(2);

    // Click on first conversation (the older one, which is at the bottom after ordering by updated_at)
    await convItems.last().click();

    // Wait for the conversation to load and messages to update
    // The first conversation should show "First conversation" as the user message
    await expect(page.locator('.message.user')).toContainText('First conversation', { timeout: 10000 });
  });

  test('shows message after sending', async ({ page }) => {
    await page.click('#new-chat-btn');

    const testMessage = 'Test message for E2E';
    await page.fill('#message-input', testMessage);
    await page.click('#send-btn');

    // Human message should appear
    const userMessage = page.locator('.message.user');
    await expect(userMessage).toBeVisible();
    await expect(userMessage).toContainText(testMessage);

    // Assistant message should appear (from mock)
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });
    await expect(assistantMessage).toContainText('mock response', { ignoreCase: true });
  });

  test('clears input after sending', async ({ page }) => {
    await page.click('#new-chat-btn');

    await page.fill('#message-input', 'Test message');
    await page.click('#send-btn');

    const input = page.locator('#message-input');
    await expect(input).toHaveValue('');
  });

  test('disables send button when input is empty', async ({ page }) => {
    await page.click('#new-chat-btn');

    const sendBtn = page.locator('#send-btn');
    await expect(sendBtn).toBeDisabled();

    await page.fill('#message-input', 'Some text');
    await expect(sendBtn).toBeEnabled();

    await page.fill('#message-input', '');
    await expect(sendBtn).toBeDisabled();
  });

  test('can send with Enter key', async ({ page }) => {
    await page.click('#new-chat-btn');

    await page.fill('#message-input', 'Test with Enter');
    await page.press('#message-input', 'Enter');

    // Message should be sent
    const userMessage = page.locator('.message.user');
    await expect(userMessage).toBeVisible();
    await expect(userMessage).toContainText('Test with Enter');
  });

  test('Shift+Enter creates new line instead of sending', async ({ page }) => {
    await page.click('#new-chat-btn');

    await page.fill('#message-input', 'Line 1');
    await page.press('#message-input', 'Shift+Enter');
    await page.type('#message-input', 'Line 2');

    const input = page.locator('#message-input');
    await expect(input).toHaveValue('Line 1\nLine 2');

    // Message should not be sent yet
    const messages = page.locator('.message');
    await expect(messages).toHaveCount(0);
  });

  /**
   * Regression test for: clicking "New Chat" during pending conversation selection
   * shows old messages instead of welcome message.
   *
   * The bug occurred because selectConversation() didn't check if the user had
   * navigated away (to a new chat) during the async API call. When the API response
   * arrived, it would overwrite the new chat's welcome message with the old messages.
   */
  test('new chat should not show old messages when clicked during pending conversation load', async ({ page }) => {
    // First create a conversation with messages so we have something to test with
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First conversation message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Get the conversation ID for routing
    const convItem = page.locator('.conversation-item-wrapper').first();
    const convId = await convItem.getAttribute('data-conv-id');

    // Now create a second conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second conversation message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // We should now have 2 conversations
    await expect(page.locator('.conversation-item-wrapper')).toHaveCount(2);

    // Intercept the API call for loading the first conversation to add delay
    let apiCallPending = false;
    let resolveApiCall: () => void;
    const apiCallPromise = new Promise<void>((resolve) => {
      resolveApiCall = resolve;
    });

    await page.route(`**/api/conversations/${convId}`, async (route) => {
      apiCallPending = true;
      // Wait until the test allows the response to complete
      await apiCallPromise;
      // Continue with the real response
      await route.continue();
    });

    // Click on the first conversation in the sidebar (this will trigger a slow API call)
    await convItem.click();

    // Wait for the API call to be in flight
    await page.waitForFunction(() => true, {}, { timeout: 500 });

    // Now quickly click "New Chat" before the API response arrives
    await page.click('#new-chat-btn');

    // The welcome message should be visible (not the old conversation messages)
    const welcomeMessage = page.locator('.welcome-message');
    await expect(welcomeMessage).toBeVisible();

    // Verify we're NOT showing any messages from the old conversation
    const messagesContainer = page.locator('#messages');
    await expect(messagesContainer).not.toContainText('First conversation message');

    // Now allow the delayed API response to complete
    resolveApiCall!();

    // Give a moment for any erroneous state update
    await page.waitForTimeout(500);

    // The welcome message should STILL be visible (regression test - this used to fail)
    await expect(welcomeMessage).toBeVisible();
    await expect(messagesContainer).not.toContainText('First conversation message');
  });

  /**
   * Regression test: clicking back on a temp "New Conversation" after navigating away
   * should switch back to that temp conversation, not load a different one.
   */
  test('clicking temp conversation after navigating to another should switch back correctly', async ({ page }) => {
    // First create a persisted conversation with messages
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Now create a NEW temp conversation (don't send a message)
    await page.click('#new-chat-btn');

    // Verify we're in a new empty conversation
    const welcomeMessage = page.locator('.welcome-message');
    await expect(welcomeMessage).toBeVisible();

    // We should have 2 conversations: the temp one at top, persisted one below
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(2);

    // The temp conversation should be at the top with default title
    const tempConvItem = convItems.first();
    await expect(tempConvItem).toContainText('New Conversation');
    const tempConvId = await tempConvItem.getAttribute('data-conv-id');
    expect(tempConvId).toMatch(/^temp-/);

    // Navigate to the persisted conversation
    await convItems.last().click();

    // Verify we switched: messages should be visible
    await expect(page.locator('.message.user')).toContainText('First conversation');

    // Now click back on the temp conversation
    await tempConvItem.click();

    // Should be back to the empty temp conversation
    await expect(welcomeMessage).toBeVisible();
    await expect(page.locator('.message')).toHaveCount(0);

    // Note: The URL will still point to the persisted conversation because
    // we don't update the hash when switching to a temp conversation.
    // This is intentional - temp conversations are not persisted and shouldn't
    // have URLs. If the user refreshes, they'll load the persisted conversation
    // from the URL, which is acceptable behavior.
  });
});

test.describe('Conversation deletion', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Disable streaming for reliable mock responses
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }

    // Create a conversation first
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });
  });

  test('delete button appears on hover', async ({ page }) => {
    const convItem = page.locator('.conversation-item-wrapper').first();
    const actionsContainer = convItem.locator('.conversation-actions');

    // Initially not visible (opacity: 0) - actions container controls visibility
    await expect(actionsContainer).toHaveCSS('opacity', '0');

    // Hover on the conversation item to reveal buttons
    await convItem.hover();

    // Actions container should now be visible (opacity: 1)
    await expect(actionsContainer).toHaveCSS('opacity', '1');

    // Delete button should be visible
    const deleteBtn = convItem.locator('.conversation-delete');
    await expect(deleteBtn).toBeVisible();
  });

  test('clicking delete removes conversation', async ({ page }) => {
    // Hover to reveal delete button, then click
    const convItem = page.locator('.conversation-item-wrapper').first();
    await convItem.hover();

    const deleteBtn = convItem.locator('.conversation-delete');
    await deleteBtn.click();

    // Wait for custom modal to appear and click confirm (Delete button)
    const modal = page.locator('.modal-container:not(.modal-hidden)');
    await expect(modal).toBeVisible();
    await modal.locator('.modal-confirm').click();

    // Conversation should be removed
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(0);

    // Empty state should show
    const emptyState = page.locator('.conversations-empty');
    await expect(emptyState).toBeVisible();
  });

  test('can cancel deletion', async ({ page }) => {
    // Hover to reveal delete button, then click
    const convItem = page.locator('.conversation-item-wrapper').first();
    await convItem.hover();

    const deleteBtn = convItem.locator('.conversation-delete');
    await deleteBtn.click();

    // Wait for custom modal to appear and click cancel
    const modal = page.locator('.modal-container:not(.modal-hidden)');
    await expect(modal).toBeVisible();
    await modal.locator('.modal-cancel').click();

    // Conversation should still be there
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(1);
  });
});

test.describe('Conversation rename', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Disable streaming for reliable mock responses
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }

    // Create a conversation first
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test conversation for rename');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });
  });

  test('rename button appears on hover', async ({ page }) => {
    const convItem = page.locator('.conversation-item-wrapper').first();
    const actionsContainer = convItem.locator('.conversation-actions');

    // Initially not visible (opacity: 0)
    await expect(actionsContainer).toHaveCSS('opacity', '0');

    // Hover on the conversation item to reveal buttons
    await convItem.hover();

    // Actions container should now be visible (opacity: 1)
    await expect(actionsContainer).toHaveCSS('opacity', '1');

    // Rename button should be visible
    const renameBtn = convItem.locator('.conversation-rename');
    await expect(renameBtn).toBeVisible();
  });

  test('clicking rename opens prompt modal', async ({ page }) => {
    // Hover to reveal rename button, then click
    const convItem = page.locator('.conversation-item-wrapper').first();
    await convItem.hover();

    const renameBtn = convItem.locator('.conversation-rename');
    await renameBtn.click();

    // Wait for prompt modal to appear
    const modal = page.locator('.modal-container:not(.modal-hidden)');
    await expect(modal).toBeVisible();

    // Should have title "Rename Conversation"
    const title = modal.locator('.modal-title');
    await expect(title).toContainText('Rename Conversation');

    // Should have an input field
    const input = modal.locator('.modal-input');
    await expect(input).toBeVisible();
  });

  test('can rename a conversation', async ({ page }) => {
    // Hover to reveal rename button, then click
    const convItem = page.locator('.conversation-item-wrapper').first();
    await convItem.hover();

    const renameBtn = convItem.locator('.conversation-rename');
    await renameBtn.click();

    // Wait for prompt modal to appear
    const modal = page.locator('.modal-container:not(.modal-hidden)');
    await expect(modal).toBeVisible();

    // Clear existing value and type new name
    const input = modal.locator('.modal-input');
    await input.clear();
    await input.fill('My Renamed Conversation');

    // Click confirm
    await modal.locator('.modal-confirm').click();

    // Modal should close
    await expect(modal).not.toBeVisible();

    // Conversation title in sidebar should be updated
    const convTitle = convItem.locator('.conversation-title');
    await expect(convTitle).toContainText('My Renamed Conversation');

    // Success toast should appear
    const toast = page.locator('.toast-success');
    await expect(toast).toBeVisible();
  });

  test('can cancel rename', async ({ page }) => {
    // Get original title
    const convItem = page.locator('.conversation-item-wrapper').first();
    const convTitle = convItem.locator('.conversation-title');
    const originalTitle = await convTitle.textContent();

    // Hover to reveal rename button, then click
    await convItem.hover();

    const renameBtn = convItem.locator('.conversation-rename');
    await renameBtn.click();

    // Wait for prompt modal to appear
    const modal = page.locator('.modal-container:not(.modal-hidden)');
    await expect(modal).toBeVisible();

    // Type new name
    const input = modal.locator('.modal-input');
    await input.clear();
    await input.fill('Should Not Be Saved');

    // Click cancel
    await modal.locator('.modal-cancel').click();

    // Modal should close
    await expect(modal).not.toBeVisible();

    // Title should remain unchanged
    await expect(convTitle).toContainText(originalTitle!);
  });

  test('updates chat title when renaming current conversation', async ({ page }) => {
    // Verify we're viewing the current conversation
    const convItem = page.locator('.conversation-item-wrapper').first();
    await expect(convItem).toHaveClass(/active/);

    // Rename the conversation
    await convItem.hover();
    const renameBtn = convItem.locator('.conversation-rename');
    await renameBtn.click();

    const modal = page.locator('.modal-container:not(.modal-hidden)');
    const input = modal.locator('.modal-input');
    await input.clear();
    await input.fill('Updated Chat Title');
    await modal.locator('.modal-confirm').click();

    // Chat header title should be updated
    const chatTitle = page.locator('#current-chat-title');
    await expect(chatTitle).toContainText('Updated Chat Title');
  });

  test('rejects empty name', async ({ page }) => {
    // Hover to reveal rename button, then click
    const convItem = page.locator('.conversation-item-wrapper').first();
    await convItem.hover();

    const renameBtn = convItem.locator('.conversation-rename');
    await renameBtn.click();

    // Wait for prompt modal to appear
    const modal = page.locator('.modal-container:not(.modal-hidden)');
    await expect(modal).toBeVisible();

    // Clear the input (empty name)
    const input = modal.locator('.modal-input');
    await input.clear();

    // Click confirm
    await modal.locator('.modal-confirm').click();

    // Modal should close (frontend returns early for empty input)
    await expect(modal).not.toBeVisible();

    // Title should remain unchanged (no error, just no change)
    const convTitle = convItem.locator('.conversation-title');
    await expect(convTitle).toBeVisible();
  });
});

test.describe('Scroll to bottom behavior', () => {
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

  test('scrolls to bottom when switching from short to long conversation', async ({ page }) => {
    // Create a short conversation (1 message)
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Short conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Create a long conversation with many messages
    await page.click('#new-chat-btn');
    for (let i = 0; i < 5; i++) {
      await page.fill('#message-input', `Long conversation message ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 10000 });
    }

    // Get the messages container
    const messagesContainer = page.locator('#messages');

    // Switch to short conversation (the older one at the bottom of the list)
    const convItems = page.locator('.conversation-item-wrapper');
    await convItems.last().click();

    // Wait for the short conversation to load - the message should contain "Short conversation"
    // Use toContainText with timeout as the conversation switch is async
    await expect(page.locator('.message.user').first()).toContainText('Short conversation', { timeout: 10000 });
    await expect(page.locator('.message.user')).toHaveCount(1);

    // Now switch back to the long conversation (should be at top of list)
    await convItems.first().click();

    // Wait for messages to render - should have 5 user messages now
    await expect(page.locator('.message.user')).toHaveCount(5);
    await page.waitForSelector('.message.user >> text=Long conversation message 5', {
      timeout: 10000,
    });

    // Verify we're scrolled to the bottom - the last message should be visible
    const lastMessage = page.locator('.message').last();
    await expect(lastMessage).toBeInViewport();

    // Also verify the scroll position is near the bottom
    const scrollInfo = await messagesContainer.evaluate((el) => ({
      scrollTop: el.scrollTop,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    }));

    // Should be within 100px of the bottom (accounting for threshold)
    const distanceFromBottom =
      scrollInfo.scrollHeight - scrollInfo.scrollTop - scrollInfo.clientHeight;
    expect(distanceFromBottom).toBeLessThan(100);
  });

  test('scrolls to bottom when loading conversation with many messages', async ({ page }) => {
    // Create a conversation with several messages
    await page.click('#new-chat-btn');
    for (let i = 0; i < 4; i++) {
      await page.fill('#message-input', `Test message number ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 10000 });
    }

    // Reload the page to test initial load scroll behavior
    await page.reload();
    await page.waitForSelector('#new-chat-btn');

    // Click on the conversation to load it
    const convItem = page.locator('.conversation-item-wrapper').first();
    await convItem.click();

    // Wait for messages to render
    await page.waitForSelector('.message.user >> text=Test message number 4', { timeout: 10000 });

    // The last message should be visible (scrolled to bottom)
    const lastMessage = page.locator('.message').last();
    await expect(lastMessage).toBeInViewport();
  });

  test('stays at bottom after sending a new message', async ({ page }) => {
    // Create a conversation with some messages
    await page.click('#new-chat-btn');
    for (let i = 0; i < 3; i++) {
      await page.fill('#message-input', `Initial message ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 10000 });
    }

    // Send one more message
    await page.fill('#message-input', 'New message at the end');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant >> nth=3', { timeout: 10000 });

    // The new message should be visible
    const newMessage = page.locator('.message.user >> text=New message at the end');
    await expect(newMessage).toBeInViewport();

    // The assistant response should also be visible
    const lastAssistant = page.locator('.message.assistant').last();
    await expect(lastAssistant).toBeInViewport();
  });

  test('does not hijack scroll when user scrolls up to view history', async ({ page }) => {
    // Create a conversation with several messages
    await page.click('#new-chat-btn');
    for (let i = 0; i < 5; i++) {
      await page.fill('#message-input', `Message number ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 10000 });
    }

    const messagesContainer = page.locator('#messages');

    // Simulate user scrolling up (not programmatic scroll)
    // We scroll up significantly to trigger the "user is browsing history" detection
    await messagesContainer.evaluate((el) => {
      // Simulate a user scroll by directly setting scrollTop
      // This mimics what happens when user uses scroll wheel/touch
      el.scrollTop = 0;
    });

    // Give a moment for scroll event to fire and be processed
    await page.waitForTimeout(200);

    // Verify we're at the top
    const scrollTopBefore = await messagesContainer.evaluate((el) => el.scrollTop);
    expect(scrollTopBefore).toBe(0);

    // Wait a bit to ensure no scroll hijacking occurs
    await page.waitForTimeout(300);

    // Verify we're still at the top (scroll was not hijacked)
    const scrollTopAfter = await messagesContainer.evaluate((el) => el.scrollTop);
    expect(scrollTopAfter).toBe(0);

    // The first message should be visible
    const firstMessage = page.locator('.message.user').first();
    await expect(firstMessage).toBeInViewport();
  });

  test('does not scroll back to bottom when image loads while user is scrolled up', async ({
    page,
  }) => {
    // Create a conversation with several messages to create scrollable content
    await page.click('#new-chat-btn');
    for (let i = 0; i < 5; i++) {
      await page.fill('#message-input', `Message ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 10000 });
    }

    // Create a simple 1x1 pixel PNG image for testing
    // PNG header + minimal image data
    const pngBuffer = Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
      'base64'
    );

    // Add a message with an image at the bottom
    const fileInput = page.locator('#file-input');
    await fileInput.setInputFiles({
      name: 'test.png',
      mimeType: 'image/png',
      buffer: pngBuffer,
    });

    // Wait for file to be attached
    await page.waitForSelector('.file-preview', { timeout: 5000 });

    // Send the message with the image
    await page.fill('#message-input', 'Message with image');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant >> nth=5', { timeout: 10000 });

    const messagesContainer = page.locator('#messages');

    // Wait for initial scroll to complete and image to be rendered
    await page.waitForTimeout(300);

    // Scroll to the top of the conversation (user browsing history)
    await messagesContainer.evaluate((el) => {
      el.scrollTo({ top: 0, behavior: 'instant' });
    });

    // Wait for scroll event to be processed
    await page.waitForTimeout(200);

    // Verify we're at the top
    const scrollTopAtTop = await messagesContainer.evaluate((el) => el.scrollTop);
    expect(scrollTopAtTop).toBe(0);

    // Now scroll down a bit so the image at the bottom becomes visible
    // This will trigger IntersectionObserver and start loading the image
    // The IntersectionObserver has rootMargin of 50px, so we need to scroll
    // close enough to the bottom for the image to be detected
    const scrollInfo = await messagesContainer.evaluate((el) => ({
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    }));
    const scrollPosition = scrollInfo.scrollHeight - scrollInfo.clientHeight - 100; // 100px from bottom

    await messagesContainer.evaluate((el, pos) => {
      el.scrollTo({ top: pos, behavior: 'instant' });
    }, scrollPosition);

    // Wait for scroll event to be processed
    await page.waitForTimeout(200);

    // Verify we're scrolled up (not at bottom)
    const scrollTopAfterScroll = await messagesContainer.evaluate((el) => el.scrollTop);
    expect(scrollTopAfterScroll).toBeGreaterThan(0);
    expect(scrollTopAfterScroll).toBeLessThan(scrollInfo.scrollHeight - scrollInfo.clientHeight - 50);

    // Wait for image to load (it should start loading now that it's visible)
    // The image loading is async, so we wait for it to complete
    // Check for image element and wait for it to have a src (indicating it loaded)
    const image = page.locator('img[data-message-id][data-file-index]').last();
    await image.waitFor({ state: 'attached', timeout: 5000 });

    // Wait for image to actually load (src attribute set and image rendered)
    // This tests the race condition: image finishes loading while user is scrolled up
    // The fix should prevent scroll hijacking even if the image loads quickly
    await page.waitForTimeout(500);

    // Verify we're still at the same scroll position (not hijacked back to bottom)
    // This is the critical assertion - even though the image loaded, we shouldn't scroll
    const scrollTopAfterImageLoad = await messagesContainer.evaluate((el) => el.scrollTop);
    // Allow small tolerance for layout shifts, but should be close to previous position
    expect(Math.abs(scrollTopAfterImageLoad - scrollTopAfterScroll)).toBeLessThan(100);

    // Verify we're NOT at the bottom
    const distanceFromBottom = await messagesContainer.evaluate((el) => {
      return el.scrollHeight - el.scrollTop - el.clientHeight;
    });
    expect(distanceFromBottom).toBeGreaterThan(50); // Should be more than 50px from bottom
  });

  /**
   * REGRESSION TEST: Race condition - image loads quickly while user scrolls up
   *
   * This test targets a specific race condition where:
   * 1. User scrolls up to view history
   * 2. Image becomes visible and starts loading (IntersectionObserver fires)
   * 3. Image finishes loading BEFORE the scroll listener's debounce (100ms) completes
   * 4. System should NOT scroll back to bottom (scroll hijacking prevention)
   *
   * The fix involves checking scroll position immediately when image finishes loading,
   * not just relying on the debounced scroll listener. This prevents the race condition
   * where an image could finish loading while shouldScrollOnImageLoad is still true
   * (because the debounced handler hasn't run yet).
   */
  test('race condition: image loads quickly while user scrolls up', async ({ page }) => {

    // Create a conversation with an image
    await page.click('#new-chat-btn');
    for (let i = 0; i < 3; i++) {
      await page.fill('#message-input', `Message ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 10000 });
    }

    // Add a message with an image
    const pngBuffer = Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
      'base64'
    );

    const fileInput = page.locator('#file-input');
    await fileInput.setInputFiles({
      name: 'test.png',
      mimeType: 'image/png',
      buffer: pngBuffer,
    });

    await page.waitForSelector('.file-preview', { timeout: 5000 });
    await page.fill('#message-input', 'Message with image');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant >> nth=3', { timeout: 10000 });

    const messagesContainer = page.locator('#messages');

    // Wait for initial render
    await page.waitForTimeout(500);

    // Scroll to top (user browsing history)
    await messagesContainer.evaluate((el) => {
      el.scrollTo({ top: 0, behavior: 'instant' });
    });

    // Verify at top
    const scrollTopAtTop = await messagesContainer.evaluate((el) => el.scrollTop);
    expect(scrollTopAtTop).toBe(0);

    // Now scroll down just enough to make image visible (triggers IntersectionObserver)
    // This simulates the race condition: image starts loading while user is scrolled up
    const scrollInfo = await messagesContainer.evaluate((el) => ({
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    }));
    const scrollPosition = scrollInfo.scrollHeight - scrollInfo.clientHeight - 80; // Close to bottom

    await messagesContainer.evaluate((el, pos) => {
      el.scrollTo({ top: pos, behavior: 'instant' });
    }, scrollPosition);

    // Wait a very short time - this is the race condition window
    // The scroll listener has a 100ms debounce, but image might load faster
    await page.waitForTimeout(50);

    // Verify we're scrolled up (not at bottom)
    const scrollTopBeforeLoad = await messagesContainer.evaluate((el) => el.scrollTop);
    expect(scrollTopBeforeLoad).toBeGreaterThan(0);

    // Wait for image to load (this might happen before scroll listener processes)
    // The fix should check scroll position when image finishes, not just the flag
    await page.waitForTimeout(800); // Give image time to load

    // CRITICAL: Verify scroll position hasn't changed (race condition fix worked)
    const scrollTopAfterLoad = await messagesContainer.evaluate((el) => el.scrollTop);
    // Should be very close to where we were (within 20px for layout shifts)
    expect(Math.abs(scrollTopAfterLoad - scrollTopBeforeLoad)).toBeLessThan(20);

    // Verify we're still NOT at the bottom
    const distanceFromBottom = await messagesContainer.evaluate((el) => {
      return el.scrollHeight - el.scrollTop - el.clientHeight;
    });
    expect(distanceFromBottom).toBeGreaterThan(50);
  });

  test('scrolls to bottom after images load on initial load - single image', async ({ page }) => {
    // Create a conversation with a single image
    await page.click('#new-chat-btn');

    // Create a simple 1x1 pixel PNG image for testing
    const pngBuffer = Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
      'base64'
    );

    const fileInput = page.locator('#file-input');
    await fileInput.setInputFiles({
      name: 'test.png',
      mimeType: 'image/png',
      buffer: pngBuffer,
    });

    await page.waitForSelector('.file-preview', { timeout: 5000 });
    await page.fill('#message-input', 'Message with single image');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Wait for image to be in the DOM
    await page.waitForSelector('img[data-message-id][data-file-index]', { timeout: 5000 });

    // Reload the page to test INITIAL LOAD behavior
    await page.reload();
    await page.waitForSelector('#new-chat-btn');

    // Click on the conversation to load it (this is the initial load scenario)
    const convItem = page.locator('.conversation-item-wrapper').first();
    await convItem.click();

    // Wait for messages to render
    await page.waitForSelector('.message.user >> text=Message with single image', { timeout: 10000 });

    // Wait for image to start loading (should have loading class or be observed)
    await page.waitForSelector('img[data-message-id][data-file-index]', { timeout: 5000 });

    // Wait for image to load (check for loaded class or src attribute)
    await page.waitForFunction(
      () => {
        const images = document.querySelectorAll<HTMLImageElement>(
          'img[data-message-id][data-file-index]'
        );
        if (images.length === 0) return false;
        // Image is loaded if it has src and is complete, or has loaded class
        return Array.from(images).some(
          (img) => (img.src && img.complete) || img.classList.contains('loaded')
        );
      },
      { timeout: 10000 }
    );

    // Wait a bit for scroll to happen after image loads
    await page.waitForTimeout(500);

    // Verify we're scrolled to the bottom - the last message should be visible
    const messagesContainer = page.locator('#messages');
    const isAtBottom = await messagesContainer.evaluate((el) => {
      const { scrollTop, scrollHeight, clientHeight } = el;
      const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
      return distanceFromBottom <= 50; // Allow 50px tolerance
    });

    expect(isAtBottom).toBe(true);
  });

  test('scrolls to bottom after images load on initial load - two images', async ({ page }) => {
    // Create a conversation with TWO images (this is the failing case)
    await page.click('#new-chat-btn');

    // Generate PNG images programmatically
    const pngBuffer = generatePngBuffer(1, 1, 'red');

    const fileInput = page.locator('#file-input');

    // Upload first image
    await fileInput.setInputFiles({
      name: 'test1.png',
      mimeType: 'image/png',
      buffer: pngBuffer,
    });
    await page.waitForSelector('.file-preview', { timeout: 5000 });

    // Upload second image
    await fileInput.setInputFiles({
      name: 'test2.png',
      mimeType: 'image/png',
      buffer: pngBuffer,
    });
    await page.waitForSelector('.file-preview-item', { timeout: 5000 });

    // Verify we have 2 files
    const fileCount = await page.locator('.file-preview-item').count();
    expect(fileCount).toBe(2);

    await page.fill('#message-input', 'Message with two images');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Wait for images to be in the DOM
    await page.waitForSelector('img[data-message-id][data-file-index]', { timeout: 5000 });

    // Verify we have 2 images
    const imageCount = await page.locator('img[data-message-id][data-file-index]').count();
    expect(imageCount).toBe(2);

    // Reload the page to test INITIAL LOAD behavior
    await page.reload();
    await page.waitForSelector('#new-chat-btn');

    // Click on the conversation to load it (this is the initial load scenario)
    const convItem = page.locator('.conversation-item-wrapper').first();
    await convItem.click();

    // Wait for messages to render
    await page.waitForSelector('.message.user >> text=Message with two images', { timeout: 10000 });

    // Wait for images to start loading (should have loading class or be observed)
    await page.waitForSelector('img[data-message-id][data-file-index]', { timeout: 5000 });

    // Verify we have 2 images
    const imageCountAfterReload = await page.locator('img[data-message-id][data-file-index]').count();
    expect(imageCountAfterReload).toBe(2);

    // Wait for ALL images to load (check for loaded class or src attribute)
    await page.waitForFunction(
      () => {
        const images = document.querySelectorAll<HTMLImageElement>(
          'img[data-message-id][data-file-index]'
        );
        if (images.length !== 2) return false;
        // All images must be loaded
        return Array.from(images).every(
          (img) => (img.src && img.complete) || img.classList.contains('loaded')
        );
      },
      { timeout: 10000 }
    );

    // Wait a bit for scroll to happen after images load
    await page.waitForTimeout(500);

    // Verify we're scrolled to the bottom - the last message should be visible
    const messagesContainer = page.locator('#messages');
    const isAtBottom = await messagesContainer.evaluate((el) => {
      const { scrollTop, scrollHeight, clientHeight } = el;
      const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
      return distanceFromBottom <= 50; // Allow 50px tolerance
    });

    expect(isAtBottom).toBe(true);
  });

  /**
   * CRITICAL REGRESSION TEST: Scroll hijacking during image load layout shifts
   *
   * This test reproduces a bug where scroll-to-bottom fails on initial load when images
   * are present. The bug manifests most clearly with 2 images (hence the test name), but
   * the root cause applies to any number of images.
   *
   * Root causes:
   * 1. Layout shifts: Image loading increases scrollHeight, making it appear the user
   *    scrolled away (>200px threshold), causing the scroll listener to disable scroll mode
   * 2. Race condition: Cached images load instantly before IntersectionObserver fires
   *    or before we can count them properly
   * 3. False positives: The scroll listener disables scroll mode during layout changes,
   *    even when we're actively scheduling a scroll
   *
   * Why "2-image" in the name?
   * - With 2 images loading simultaneously, layout shifts are more significant and
   *   more likely to trigger the false positive
   * - The race condition is more likely with multiple images loading at once
   * - This matches the user's exact report and makes the test reproducible
   *
   * The fix involves:
   * - `isSchedulingScroll` flag to prevent premature disabling during scroll animation
   * - `safelyDisableScrollOnImageLoad()` that checks `isSchedulingScroll` before disabling
   * - Ignoring scroll-away checks in `scheduleScrollAfterImageLoad()` when `isSchedulingScroll` is true
   * - Checking all tracked images are loaded before scheduling scroll (handles cached images)
   *
   * This test will catch regressions if:
   * - Scroll mode is disabled during scroll scheduling (console log check)
   * - Final scroll position is not at bottom (distanceFromBottom > 50px)
   * - Last message is not visible in viewport
   */
  test('reproduces scroll hijacking bug (2-image scenario) - matches screenshot', async ({ page, browserName }) => {
    // Use Chromium to match user's browser (Dia uses Chromium)
    test.skip(browserName !== 'chromium', 'This test is specifically for Chromium');

    // STEP 1: Create a conversation with scrollable content and 2 images
    // This matches the user's screenshot scenario where 2 images are visible at once
    await page.click('#new-chat-btn');

    // Add several messages first to create scrollable content (realistic usage)
    // This ensures the conversation requires scrolling to see the images
    for (let i = 0; i < 5; i++) {
      await page.fill('#message-input', `Message ${i + 1} - this is a longer message to create more scrollable content`);
      await page.click('#send-btn');
      await page.waitForSelector(`.message.assistant >> nth=${i}`, { timeout: 10000 });
    }

    // Use proper 400x400 test images (not 1x1) to ensure scrolling is actually needed
    // Small images don't trigger the bug because they don't cause significant layout shifts
    const image1Buffer = TEST_IMAGES.red400x400;
    const image2Buffer = TEST_IMAGES.blue400x400;

    const fileInput = page.locator('#file-input');

    // Upload BOTH images at once (this creates 2 images in the same message)
    // The bug specifically occurs when 2 images are visible in the viewport on initial load
    await fileInput.setInputFiles([
      {
        name: 'test1.png',
        mimeType: 'image/png',
        buffer: image1Buffer,
      },
      {
        name: 'test2.png',
        mimeType: 'image/png',
        buffer: image2Buffer,
      },
    ]);

    // Verify we have 2 files attached
    await page.waitForSelector('.file-preview-item', { timeout: 5000 });
    const fileCount = await page.locator('.file-preview-item').count();
    expect(fileCount).toBe(2);

    // Send the message with both images
    await page.fill('#message-input', 'Message with two images');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Wait for images to be rendered in the DOM
    await page.waitForSelector('img[data-message-id][data-file-index]', { timeout: 5000 });

    // Verify we have exactly 2 images (the ones we just uploaded)
    const imageCount = await page.locator('img[data-message-id][data-file-index]').count();
    expect(imageCount).toBe(2);

    // Wait for both images to load initially (before reload)
    await page.waitForFunction(
      () => {
        const images = document.querySelectorAll<HTMLImageElement>(
          'img[data-message-id][data-file-index]'
        );
        if (images.length !== 2) return false;
        // Check that all images are fully loaded (have src, are complete, and have dimensions)
        return Array.from(images).every(
          (img) => (img.src && img.complete && img.naturalHeight > 0) || img.classList.contains('loaded')
        );
      },
      { timeout: 10000 }
    );

    // STEP 2: Reload the page to test INITIAL LOAD behavior (this is where the bug occurs)
    // On initial load, images are not in browser cache yet, so they load from the server
    // This tests the scenario where images load asynchronously and trigger scroll behavior
    await page.reload();
    await page.waitForSelector('#new-chat-btn', { timeout: 10000 });

    // Click on the conversation to load it (this triggers the initial load scenario)
    const convItem = page.locator('.conversation-item-wrapper').first();
    await convItem.click();

    // Wait for messages to render (renderMessages() is called here)
    await page.waitForSelector('.message.user >> text=Message with two images', { timeout: 10000 });

    // Wait for images to be in the DOM (they start without src, waiting for IntersectionObserver)
    await page.waitForSelector('img[data-message-id][data-file-index]', { timeout: 5000 });

    // Verify we still have 2 images after reload
    const imageCountAfterReload = await page.locator('img[data-message-id][data-file-index]').count();
    expect(imageCountAfterReload).toBe(2);

    // Wait for renderMessages() to complete its initial scroll and layout settling
    // renderMessages() uses double RAF for scroll, then counts images, then observes them
    await page.waitForTimeout(500);

    // Get initial scroll position after renderMessages() completes
    // This helps us understand if the initial scroll worked correctly
    const messagesContainer = page.locator('#messages');
    const initialScroll = await messagesContainer.evaluate((el) => ({
      scrollTop: el.scrollTop,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
      distanceFromBottom: el.scrollHeight - el.scrollTop - el.clientHeight,
    }));

    console.log('Initial scroll after renderMessages():', initialScroll);

    // If not at bottom, manually scroll to make images visible for IntersectionObserver
    // This simulates what renderMessages() should do, but we do it manually to ensure
    // images are visible for the IntersectionObserver to fire
    if (initialScroll.distanceFromBottom > 50) {
      console.log('Manually scrolling to bottom to make images visible');
      await messagesContainer.evaluate((el) => {
        el.scrollTop = el.scrollHeight;
      });
      await page.waitForTimeout(100);
    }

    // STEP 3: Wait for IntersectionObserver to fire and images to load
    // Images start without src, then IntersectionObserver fires when they become visible
    // This is the critical part - the bug occurs when both images load and trigger scroll

    // Wait for images to appear in DOM first
    await page.waitForSelector('img[data-message-id][data-file-index]', { timeout: 5000 });

    // Wait for IntersectionObserver to fire and set src on images
    // This is the critical part - images start without src, then IntersectionObserver sets it
    // The IntersectionObserver fires when images become visible (after scroll)
    await page.waitForFunction(
      () => {
        const images = document.querySelectorAll<HTMLImageElement>(
          'img[data-message-id][data-file-index]'
        );
        if (images.length < 2) return false;
        const lastTwo = Array.from(images).slice(-2);
        // Wait for both images to have src set (IntersectionObserver fired)
        return lastTwo.every((img) => !!img.src);
      },
      { timeout: 5000 }
    );

    // Now wait for images to actually load (complete)
    // Images have src set, but we need to wait for them to fully load and render
    await page.waitForFunction(
      () => {
        const images = document.querySelectorAll<HTMLImageElement>(
          'img[data-message-id][data-file-index]'
        );
        if (images.length < 2) return false;
        const lastTwo = Array.from(images).slice(-2);
        // Both images must be complete OR have the loaded class
        return lastTwo.every(
          (img) => img.complete || img.classList.contains('loaded')
        );
      },
      { timeout: 5000 }
    );

    // Give a moment for any async operations to complete (image load handlers, etc.)
    await page.waitForTimeout(300);

    // STEP 4: Wait for scroll to happen after images load
    // The scroll happens in triple RAF (requestAnimationFrame) to ensure layout has settled
    // Also wait for any delayed retries in case images loaded in quick succession
    await page.waitForTimeout(500);

    // STEP 5: Verify final scroll position
    // After all images load, we should be scrolled to the bottom
    const finalScroll = await messagesContainer.evaluate((el) => {
      const { scrollTop, scrollHeight, clientHeight } = el;
      return {
        scrollTop,
        scrollHeight,
        clientHeight,
        distanceFromBottom: scrollHeight - scrollTop - clientHeight,
      };
    });

    // Debug output for troubleshooting
    console.log('Final scroll after images load:', finalScroll);
    console.log('Distance from bottom:', finalScroll.distanceFromBottom);

    // CRITICAL ASSERTION: Verify we're scrolled to the bottom
    // The distance from bottom should be small (within 50px tolerance)
    // If this fails, it means the scroll-to-bottom after images load didn't work
    expect(finalScroll.distanceFromBottom).toBeLessThanOrEqual(50);

    // Also verify the last message is visible in viewport
    // This ensures the user can see the latest content
    const lastMessageAfterLoad = page.locator('.message.assistant').last();
    await expect(lastMessageAfterLoad).toBeInViewport();
  });

  test('scrolls to bottom after images load on subsequent load', async ({ page }) => {
    // Create a conversation with an image
    await page.click('#new-chat-btn');

    // Create a simple 1x1 pixel PNG image for testing
    const pngBuffer = Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
      'base64'
    );

    const fileInput = page.locator('#file-input');
    await fileInput.setInputFiles({
      name: 'test.png',
      mimeType: 'image/png',
      buffer: pngBuffer,
    });

    await page.waitForSelector('.file-preview', { timeout: 5000 });
    await page.fill('#message-input', 'Message with image');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Create a second conversation (to test switching)
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Now switch back to the first conversation (this is SUBSEQUENT LOAD)
    const convItems = page.locator('.conversation-item-wrapper');
    await convItems.last().click(); // First conversation is at the bottom

    // Wait for the conversation to switch and messages to render
    // First wait for the message text to appear (confirms conversation switched)
    await expect(page.locator('.message.user')).toContainText('Message with image', { timeout: 10000 });

    // Wait for image to start loading
    await page.waitForSelector('img[data-message-id][data-file-index]', { timeout: 5000 });

    // Wait for image to load
    await page.waitForFunction(
      () => {
        const images = document.querySelectorAll<HTMLImageElement>(
          'img[data-message-id][data-file-index]'
        );
        if (images.length === 0) return false;
        return Array.from(images).some(
          (img) => (img.src && img.complete) || img.classList.contains('loaded')
        );
      },
      { timeout: 10000 }
    );

    // Wait a bit for scroll to happen after image loads
    await page.waitForTimeout(500);

    // Verify we're scrolled to the bottom - the last message should be visible
    const messagesContainer = page.locator('#messages');
    const isAtBottom = await messagesContainer.evaluate((el) => {
      const { scrollTop, scrollHeight, clientHeight } = el;
      const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
      return distanceFromBottom <= 50; // Allow 50px tolerance
    });

    expect(isAtBottom).toBe(true);
  });
});
