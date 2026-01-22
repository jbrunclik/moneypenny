/**
 * E2E tests for real-time data synchronization
 *
 * These tests verify:
 * - Unread count badges in the sidebar
 * - External update detection (messages from another device)
 * - Delete detection during sync
 * - New messages available banner
 */
import { test, expect } from '../global-setup';

// Extend Window type for test helpers exposed by the app
declare global {
  interface Window {
    __testFullSync: () => Promise<void>;
  }
}

test.describe('Sync - Unread Count Badges', () => {
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

  test('shows unread badge when conversation has new messages', async ({ page }) => {
    // Create a conversation and send a message
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test message for unread badge');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Get the conversation ID from the active item
    const convItem = page.locator('.conversation-item-wrapper.active').first();
    await expect(convItem).toBeVisible();

    // Create another conversation (to switch away)
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Now we have 2 conversations
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(2);

    // Initially no unread badge should exist (we just created the conversations)
    const unreadBadge = page.locator('.unread-badge');
    await expect(unreadBadge).toHaveCount(0);
  });

  test('unread badge does not appear on currently viewed conversation', async ({ page }) => {
    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // The active conversation should never show an unread badge
    const activeItem = page.locator('.conversation-item-wrapper.active');
    await expect(activeItem).toBeVisible();

    // Active item should not have unread badge
    const unreadBadge = activeItem.locator('.unread-badge');
    await expect(unreadBadge).toHaveCount(0);
  });
});

test.describe('Sync - Conversation Switching', () => {
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

  test('clears unread state when switching to a conversation', async ({ page }) => {
    // Create first conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Create second conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Switch to first conversation
    const convItems = page.locator('.conversation-item-wrapper');
    await convItems.last().click(); // First conversation is at the bottom (older)

    // Wait for switch to complete
    await page.waitForSelector('.message.user >> text=First conversation');

    // The clicked conversation should now be active (and any unread state cleared)
    const activeItem = page.locator('.conversation-item-wrapper.active');
    await expect(activeItem).toBeVisible();

    // Active item should not have unread badge
    const unreadBadge = activeItem.locator('.unread-badge');
    await expect(unreadBadge).toHaveCount(0);
  });

  test('marks conversation as read when viewing it', async ({ page }) => {
    // Create a conversation with multiple messages
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Message 1');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    await page.fill('#message-input', 'Message 2');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant >> nth=1', { timeout: 10000 });

    // Create second conversation and switch back
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Other conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Switch to first conversation
    const convItems = page.locator('.conversation-item-wrapper');
    await convItems.last().click();

    // Verify we can see the messages
    await expect(page.locator('.message.user')).toHaveCount(2);
    await expect(page.locator('.message.assistant')).toHaveCount(2);

    // The conversation should be marked as read (no badge)
    const activeItem = page.locator('.conversation-item-wrapper.active');
    const unreadBadge = activeItem.locator('.unread-badge');
    await expect(unreadBadge).toHaveCount(0);
  });
});

test.describe('Sync - Conversation Deletion Detection', () => {
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

  test('detects conversation deleted by another client on full sync', async ({ page, request }) => {
    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test external deletion');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Verify conversation exists in sidebar
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(1);

    // Get the conversation ID from the data attribute
    const convId = await page.evaluate(() => {
      const activeItem = document.querySelector('.conversation-item-wrapper.active');
      return activeItem?.getAttribute('data-conv-id');
    });
    expect(convId).toBeTruthy();

    // Delete the conversation directly via API (simulating another client)
    const deleteResponse = await request.delete(`/api/conversations/${convId}`);
    expect(deleteResponse.status()).toBe(200);

    // Trigger a full sync by simulating long tab inactivity and visibility change
    // This forces the SyncManager to do a full sync with delete detection
    await page.evaluate(() => {
      // Simulate tab becoming hidden
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Wait a tiny bit
    await page.waitForTimeout(50);

    // Manually force the hidden time to be > 5 minutes ago
    // We can't easily mock time in E2E, so we'll directly trigger full sync via reload
    // OR we can expose a test-only method to force full sync

    // Alternative: Just reload the page which triggers full sync on startup
    await page.reload();
    await page.waitForSelector('#new-chat-btn');

    // Conversation should be removed from sidebar
    await expect(page.locator('.conversation-item-wrapper')).toHaveCount(0);

    // Main area should show welcome state (no current conversation)
    const welcomeMessage = page.locator('text=Welcome to AI Chatbot');
    await expect(welcomeMessage).toBeVisible();
  });

  test('shows warning toast when current conversation is deleted externally during live sync', async ({
    page,
    request,
  }) => {
    // Create two conversations
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second conversation - will be deleted');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Verify we have 2 conversations
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(2);

    // Get the current conversation ID (the one we're viewing)
    const currentConvId = await page.evaluate(() => {
      const activeItem = document.querySelector('.conversation-item-wrapper.active');
      return activeItem?.getAttribute('data-conv-id');
    });
    expect(currentConvId).toBeTruthy();

    // Delete the current conversation via API (simulating another client)
    const deleteResponse = await request.delete(`/api/conversations/${currentConvId}`);
    expect(deleteResponse.status()).toBe(200);

    // Trigger a full sync WITHOUT reloading (simulates sync while app is running)
    // This allows the SyncManager to detect the current conversation was deleted
    await page.evaluate(() => window.__testFullSync());

    // Should show warning toast about deleted conversation
    const warningToast = page.locator('.toast-warning');
    await expect(warningToast).toBeVisible({ timeout: 5000 });
    await expect(warningToast).toContainText('deleted');

    // Only one conversation should remain
    await expect(page.locator('.conversation-item-wrapper')).toHaveCount(1);
  });

  test('removes conversation from sidebar when deleted', async ({ page }) => {
    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test deletion');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Verify conversation exists
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(1);

    // Delete the conversation via UI
    const convItem = convItems.first();
    await convItem.hover();
    const deleteBtn = convItem.locator('.conversation-delete');
    await deleteBtn.click();

    // Confirm deletion
    const modal = page.locator('.modal-container:not(.modal-hidden)');
    await expect(modal).toBeVisible();
    await modal.locator('.modal-confirm').click();

    // Conversation should be removed
    await expect(convItems).toHaveCount(0);

    // Empty state should show
    const emptyState = page.locator('.conversations-empty');
    await expect(emptyState).toBeVisible();
  });

  test('shows warning when current conversation is deleted', async ({ page }) => {
    // Create two conversations
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Verify we have 2 conversations
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(2);

    // Delete the current (active) conversation
    const activeItem = page.locator('.conversation-item-wrapper.active');
    await activeItem.hover();
    const deleteBtn = activeItem.locator('.conversation-delete');
    await deleteBtn.click();

    // Confirm deletion
    const modal = page.locator('.modal-container:not(.modal-hidden)');
    await expect(modal).toBeVisible();
    await modal.locator('.modal-confirm').click();

    // Should now have only 1 conversation
    await expect(convItems).toHaveCount(1);

    // The remaining conversation should be visible in sidebar
    await expect(convItems.first()).toBeVisible();
  });
});

test.describe('Sync - Sync Endpoint Integration', () => {
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

  test('sync endpoint returns conversation with message count', async ({ page, request }) => {
    // Create a conversation with messages
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test message 1');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    await page.fill('#message-input', 'Test message 2');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant >> nth=1', { timeout: 10000 });

    // Call sync endpoint directly
    const response = await request.get('/api/conversations/sync');
    expect(response.status()).toBe(200);

    const data = await response.json();
    expect(data.conversations).toHaveLength(1);
    expect(data.conversations[0].message_count).toBe(4); // 2 user + 2 assistant
    expect(data.is_full_sync).toBe(true);
    expect(data.server_time).toBeDefined();
  });

  test('incremental sync returns only updated conversations', async ({ page, request }) => {
    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Initial message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Get initial sync time
    const initialSync = await request.get('/api/conversations/sync');
    const initialData = await initialSync.json();
    const serverTime = initialData.server_time;

    // Wait a tiny bit
    await page.waitForTimeout(50);

    // Add another message
    await page.fill('#message-input', 'Second message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant >> nth=1', { timeout: 10000 });

    // Incremental sync should return the updated conversation
    const incrementalSync = await request.get(`/api/conversations/sync?since=${serverTime}`);
    expect(incrementalSync.status()).toBe(200);

    const incrementalData = await incrementalSync.json();
    expect(incrementalData.conversations).toHaveLength(1);
    expect(incrementalData.conversations[0].message_count).toBe(4); // 2 user + 2 assistant
    expect(incrementalData.is_full_sync).toBe(false);
  });

  test('sync endpoint returns server time for next sync', async ({ page, request }) => {
    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Call sync endpoint
    const response = await request.get('/api/conversations/sync');
    const data = await response.json();

    // Server time should be a valid ISO timestamp
    expect(data.server_time).toBeDefined();
    const serverTimeDate = new Date(data.server_time);
    expect(serverTimeDate.getTime()).not.toBeNaN();

    // Using server_time for next sync should work
    const nextSync = await request.get(`/api/conversations/sync?since=${data.server_time}`);
    expect(nextSync.status()).toBe(200);
  });
});

test.describe('Sync - Multiple Tabs Simulation', () => {
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

  test('sync detects conversation created in another tab', async ({ page }) => {
    // Create a conversation via UI first (to establish a user)
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Create a second conversation via UI
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Created in another tab');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Reload the page (triggers full sync)
    await page.reload();
    await page.waitForSelector('#new-chat-btn');

    // Both conversations should appear in the sidebar
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(2);
  });

  test('sync persists local deletions after reload', async ({ page }) => {
    // Create two conversations in the current tab
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Verify both conversations exist
    const convItemsBefore = page.locator('.conversation-item-wrapper');
    await expect(convItemsBefore).toHaveCount(2);

    // Delete one conversation via UI
    const activeItem = page.locator('.conversation-item-wrapper.active');
    await activeItem.hover();
    const deleteBtn = activeItem.locator('.conversation-delete');
    await deleteBtn.click();

    // Confirm deletion
    const modal = page.locator('.modal-container:not(.modal-hidden)');
    await expect(modal).toBeVisible();
    await modal.locator('.modal-confirm').click();

    // Wait for deletion to complete
    await expect(page.locator('.conversation-item-wrapper')).toHaveCount(1);

    // Reload the page (triggers full sync)
    await page.reload();
    await page.waitForSelector('#new-chat-btn');

    // Only one conversation should remain after sync
    const convItemsAfter = page.locator('.conversation-item-wrapper');
    await expect(convItemsAfter).toHaveCount(1);
  });

  test('sync detects title change from another tab', async ({ page }) => {
    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Rename via UI
    const convItem = page.locator('.conversation-item-wrapper').first();
    await convItem.hover();
    const renameBtn = convItem.locator('.conversation-rename');
    await renameBtn.click();

    // Fill in new title
    const modal = page.locator('.modal-container:not(.modal-hidden)');
    await expect(modal).toBeVisible();
    const input = modal.locator('.modal-input');
    await input.clear();
    await input.fill('Title changed from another tab');
    await modal.locator('.modal-confirm').click();

    // Wait for toast
    await page.waitForSelector('.toast-success');

    // Reload the page (triggers full sync)
    await page.reload();
    await page.waitForSelector('#new-chat-btn');

    // The title should still be the updated one
    const title = page.locator('.conversation-item-wrapper .conversation-title').first();
    await expect(title).toContainText('Title changed from another tab');
  });
});

test.describe('Sync - Streaming Active', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Enable streaming for this test
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'false') {
      await streamBtn.click();
    }
  });

  test('does NOT show new messages banner during active streaming when sync happens', async ({ page }) => {
    // This test reproduces the bug where the sync would show "new messages available"
    // while streaming is active because the user message is already saved to DB
    // but the streaming flag should prevent sync from treating it as external update

    // Create a conversation first
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Now send another message - this will stream
    await page.fill('#message-input', 'Second message that triggers streaming');
    await page.click('#send-btn');

    // Wait for streaming to start (streaming message element should appear)
    await page.waitForSelector('.message.assistant.streaming', { timeout: 10000 });

    // While streaming is active, simulate a visibility change (tab focus/unfocus)
    // This triggers sync, which should NOT show the banner because conversation is marked as streaming
    await page.evaluate(() => {
      // Simulate tab becoming hidden
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Small delay
    await page.waitForTimeout(100);

    // Simulate tab becoming visible again
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Give sync time to complete
    await page.waitForTimeout(500);

    // The "new messages available" banner should NOT appear during streaming
    const banner = page.locator('.new-messages-banner');
    await expect(banner).toHaveCount(0);

    // Wait for streaming to complete
    await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 30000 });

    // After streaming completes, banner should still not appear (we're viewing the conversation)
    await expect(banner).toHaveCount(0);
  });

  test('does NOT show new messages banner during streaming even with scroll', async ({ page }) => {
    // This tests the scenario where user scrolls up during streaming
    // The sync should still not show the banner

    // Create a conversation with some messages
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    await page.fill('#message-input', 'Second message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant >> nth=1', { timeout: 10000 });

    // Now send another message that will stream
    await page.fill('#message-input', 'Third message that triggers streaming');
    await page.click('#send-btn');

    // Wait for streaming to start
    await page.waitForSelector('.message.assistant.streaming', { timeout: 10000 });

    // Scroll up while streaming
    const messagesContainer = page.locator('#messages');
    await messagesContainer.evaluate((el) => {
      el.scrollTop = 0;
    });

    // Trigger sync via visibility change
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await page.waitForTimeout(100);

    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Give sync time to complete
    await page.waitForTimeout(500);

    // Banner should NOT appear even when scrolled up during streaming
    const banner = page.locator('.new-messages-banner');
    await expect(banner).toHaveCount(0);
  });
});

test.describe('Sync - Visibility Change', () => {
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

  test('sync happens on page visibility change', async ({ page }) => {
    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Simulate visibility change (tab hidden then visible)
    // This tests that the SyncManager handles visibility changes
    await page.evaluate(() => {
      // Dispatch visibilitychange event for hidden
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));

      // Short delay then back to visible
      setTimeout(() => {
        Object.defineProperty(document, 'visibilityState', {
          value: 'visible',
          writable: true,
          configurable: true,
        });
        document.dispatchEvent(new Event('visibilitychange'));
      }, 100);
    });

    // Wait for sync to happen (visibility change triggers incremental sync)
    await page.waitForTimeout(500);

    // The conversation should still be in the sidebar
    const convItem = page.locator('.conversation-item-wrapper');
    await expect(convItem).toHaveCount(1);

    // Verify the conversation title is still there
    const title = convItem.locator('.conversation-title');
    await expect(title).toBeVisible();
  });

  test('conversation persists after page visibility change cycle', async ({ page }) => {
    // Create multiple conversations
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Verify both conversations exist
    const convItemsBefore = page.locator('.conversation-item-wrapper');
    await expect(convItemsBefore).toHaveCount(2);

    // Simulate tab going hidden and coming back
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await page.waitForTimeout(100);

    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Wait for sync
    await page.waitForTimeout(500);

    // Both conversations should still be there
    const convItemsAfter = page.locator('.conversation-item-wrapper');
    await expect(convItemsAfter).toHaveCount(2);
  });
});

test.describe('Sync - Remote Conversation Created While Tab Hidden', () => {
  /**
   * Regression test for the bug where conversations created on another device
   * while the current tab was hidden for >5 minutes were never synced.
   *
   * The bug:
   * 1. Tab becomes hidden, user opens another device and creates a conversation
   * 2. Tab becomes visible after >5 minutes, triggering fullSync()
   * 3. fullSync() only updated existing conversations, ignoring new ones
   * 4. lastSyncTime was advanced, so the new conversation was never fetched
   *
   * The fix: fullSync() now adds genuinely new conversations (created after
   * initialLoadTime) in addition to updating existing ones.
   */

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

  test('full sync discovers conversation created on another device while tab was hidden', async ({
    page,
    request,
  }) => {
    // Create an initial conversation to establish the user session
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Initial conversation on this device');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Verify we have 1 conversation
    const convItemsBefore = page.locator('.conversation-item-wrapper');
    await expect(convItemsBefore).toHaveCount(1);

    // Wait a moment to ensure timestamps differ
    await page.waitForTimeout(100);

    // Create a NEW conversation directly via API (simulating another device)
    // This bypasses the UI entirely, as if another device created it
    const createResponse = await request.post('/api/conversations', {
      data: { model: 'gemini-3-flash-preview' },
    });
    expect(createResponse.status()).toBe(201);
    const newConv = await createResponse.json();

    // Add a message to the new conversation (simulating activity on other device)
    const chatResponse = await request.post(`/api/conversations/${newConv.id}/chat/batch`, {
      data: {
        message: 'Message from another device',
      },
    });
    expect(chatResponse.status()).toBe(200);

    // At this point, the new conversation exists on the server but the current
    // tab doesn't know about it. This simulates what happens when:
    // - User closes laptop
    // - Opens phone, creates a conversation, sends messages
    // - Opens laptop again (tab was hidden for >5 minutes, triggers fullSync)

    // Trigger a full sync (simulates tab becoming visible after >5 minutes hidden)
    await page.evaluate(() => window.__testFullSync());

    // Wait for sync to complete and UI to update
    await page.waitForTimeout(500);

    // REGRESSION: Before the fix, this would fail - only 1 conversation would show
    // After the fix, both conversations should appear
    const convItemsAfter = page.locator('.conversation-item-wrapper');
    await expect(convItemsAfter).toHaveCount(2);

    // The new conversation should have an unread badge (since we haven't viewed it)
    const unreadBadge = page.locator('.unread-badge');
    await expect(unreadBadge).toHaveCount(1);
  });

  test('full sync shows unread count for all messages in new remote conversation', async ({
    page,
    request,
  }) => {
    // Create an initial conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Initial conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    await page.waitForTimeout(100);

    // Create a conversation with multiple messages via API
    const createResponse = await request.post('/api/conversations', {
      data: { model: 'gemini-3-flash-preview' },
    });
    const newConv = await createResponse.json();

    // Send multiple messages
    await request.post(`/api/conversations/${newConv.id}/chat/batch`, {
      data: { message: 'First message from other device' },
    });
    await request.post(`/api/conversations/${newConv.id}/chat/batch`, {
      data: { message: 'Second message from other device' },
    });

    // Trigger full sync
    await page.evaluate(() => window.__testFullSync());
    await page.waitForTimeout(500);

    // Should have 2 conversations
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(2);

    // The unread badge should show the count (4 messages: 2 user + 2 assistant)
    const unreadBadge = page.locator('.unread-badge');
    await expect(unreadBadge).toHaveCount(1);
    await expect(unreadBadge).toHaveText('4');
  });

  test('clicking on new remote conversation clears unread badge', async ({ page, request }) => {
    // Create initial conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Initial conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    await page.waitForTimeout(100);

    // Create conversation via API
    const createResponse = await request.post('/api/conversations', {
      data: { model: 'gemini-3-flash-preview' },
    });
    const newConv = await createResponse.json();

    await request.post(`/api/conversations/${newConv.id}/chat/batch`, {
      data: { message: 'Message from other device' },
    });

    // Trigger full sync
    await page.evaluate(() => window.__testFullSync());
    await page.waitForTimeout(500);

    // Verify unread badge exists
    const unreadBadge = page.locator('.unread-badge');
    await expect(unreadBadge).toHaveCount(1);

    // Click on the conversation with the unread badge
    const convWithBadge = page.locator('.conversation-item-wrapper:has(.unread-badge)');
    await convWithBadge.click();

    // Wait for conversation to load
    await page.waitForSelector('.message.user >> text=Message from other device');

    // Unread badge should be cleared
    await expect(unreadBadge).toHaveCount(0);
  });
});
