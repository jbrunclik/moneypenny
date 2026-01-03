/**
 * E2E tests for deep linking functionality
 *
 * Deep linking allows users to bookmark, share, and reload conversations via URL hash.
 * Format: #/conversations/{conversationId}
 */
import { test, expect } from '../global-setup';

test.describe('Deep Linking', () => {
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

  test('updates URL hash when switching to a conversation', async ({ page }) => {
    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Hello, test message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Get the conversation ID from the sidebar
    const convItem = page.locator('.conversation-item-wrapper').first();
    const convId = await convItem.getAttribute('data-conv-id');
    expect(convId).toBeTruthy();

    // Check URL hash is set
    const hash = await page.evaluate(() => window.location.hash);
    expect(hash).toBe(`#/conversations/${convId}`);
  });

  test('does not update URL hash for temp conversations', async ({ page }) => {
    // Create a new chat (temp conversation - not yet persisted)
    await page.click('#new-chat-btn');

    // Hash should be empty for temp conversations
    const hash = await page.evaluate(() => window.location.hash);
    expect(hash).toBe('');
  });

  test('updates URL hash after temp conversation is persisted', async ({ page }) => {
    // Create a temp conversation
    await page.click('#new-chat-btn');

    // Before sending, hash should be empty
    let hash = await page.evaluate(() => window.location.hash);
    expect(hash).toBe('');

    // Send a message to persist the conversation
    await page.fill('#message-input', 'Persist this conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // After persisting, hash should be set
    hash = await page.evaluate(() => window.location.hash);
    expect(hash).toMatch(/^#\/conversations\/[a-zA-Z0-9-]+$/);
    expect(hash).not.toContain('temp-');
  });

  test('loads conversation from URL hash on page reload', async ({ page }) => {
    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Deep link test message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Get the conversation ID
    const hash = await page.evaluate(() => window.location.hash);
    expect(hash).toMatch(/^#\/conversations\/[a-zA-Z0-9-]+$/);

    // Reload the page with the hash
    await page.reload();
    await page.waitForSelector('#new-chat-btn');

    // Conversation should be loaded automatically
    const userMessage = page.locator('.message.user');
    await expect(userMessage).toBeVisible({ timeout: 10000 });
    await expect(userMessage).toContainText('Deep link test message');

    // URL hash should still be set
    const hashAfterReload = await page.evaluate(() => window.location.hash);
    expect(hashAfterReload).toBe(hash);
  });

  test('clears URL hash when conversation is deleted', async ({ page }) => {
    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Conversation to delete');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Verify hash is set
    let hash = await page.evaluate(() => window.location.hash);
    expect(hash).toMatch(/^#\/conversations\/[a-zA-Z0-9-]+$/);

    // Delete the conversation
    const convItem = page.locator('.conversation-item-wrapper').first();
    await convItem.hover();
    const deleteBtn = convItem.locator('.conversation-delete');
    await deleteBtn.click();

    // Confirm deletion
    const modal = page.locator('.modal-container:not(.modal-hidden)');
    await expect(modal).toBeVisible();
    await modal.locator('.modal-confirm').click();

    // Wait for conversation to be removed
    await expect(convItem).not.toBeVisible();

    // Hash should be cleared
    hash = await page.evaluate(() => window.location.hash);
    expect(hash).toBe('');
  });

  test('clears URL hash when creating a new conversation', async ({ page }) => {
    // Create a conversation first
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Verify hash is set
    let hash = await page.evaluate(() => window.location.hash);
    expect(hash).toMatch(/^#\/conversations\/[a-zA-Z0-9-]+$/);

    // Create a new conversation
    await page.click('#new-chat-btn');

    // Hash should be cleared for temp conversation
    hash = await page.evaluate(() => window.location.hash);
    expect(hash).toBe('');
  });

  test('handles invalid conversation ID in URL gracefully', async ({ page }) => {
    // Navigate to a non-existent conversation
    await page.goto('/#/conversations/non-existent-id-12345');
    await page.waitForSelector('#new-chat-btn');

    // Should show error toast
    const toast = page.locator('.toast-error');
    await expect(toast).toBeVisible({ timeout: 10000 });
    await expect(toast).toContainText("Conversation not found");

    // Hash should be cleared
    const hash = await page.evaluate(() => window.location.hash);
    expect(hash).toBe('');
  });

  test('browser back button navigates between conversations', async ({ page }) => {
    // Create first conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    const firstHash = await page.evaluate(() => window.location.hash);

    // Create second conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Second conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    const secondHash = await page.evaluate(() => window.location.hash);
    expect(secondHash).not.toBe(firstHash);

    // Press browser back button
    await page.goBack();

    // Should navigate to first conversation
    await page.waitForSelector('.message.user >> text=First conversation', { timeout: 10000 });
    const userMessage = page.locator('.message.user');
    await expect(userMessage).toContainText('First conversation');

    // Hash should be first conversation
    const hash = await page.evaluate(() => window.location.hash);
    expect(hash).toBe(firstHash);
  });

  test('browser forward button navigates to next conversation', async ({ page }) => {
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

    const secondHash = await page.evaluate(() => window.location.hash);

    // Go back to first
    await page.goBack();
    await page.waitForSelector('.message.user >> text=First conversation', { timeout: 10000 });

    // Go forward to second
    await page.goForward();
    await page.waitForSelector('.message.user >> text=Second conversation', { timeout: 10000 });

    // Hash should be second conversation
    const hash = await page.evaluate(() => window.location.hash);
    expect(hash).toBe(secondHash);
  });

  test('switching conversations via sidebar adds to browser history', async ({ page }) => {
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

    // Click on first conversation in sidebar
    const convItems = page.locator('.conversation-item-wrapper');
    await convItems.last().click();
    await page.waitForSelector('.message.user >> text=First conversation', { timeout: 10000 });

    const firstHash = await page.evaluate(() => window.location.hash);

    // Go back should return to second conversation
    await page.goBack();
    await page.waitForSelector('.message.user >> text=Second conversation', { timeout: 10000 });

    const hash = await page.evaluate(() => window.location.hash);
    expect(hash).not.toBe(firstHash);
  });
});

test.describe('Deep Linking - Not in Paginated List', () => {
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

  test('loads conversation from URL that is not in initial pagination', async ({ page }) => {
    // Create multiple conversations to push beyond pagination
    // We need to create conversations via API to simulate the scenario
    // where a deep link points to a conversation not in the initial list

    // Create first conversation and get its ID
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'First message for deep link test');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    const firstConvHash = await page.evaluate(() => window.location.hash);
    const firstConvId = firstConvHash.replace('#/conversations/', '');

    // Create many more conversations to push the first one beyond pagination
    for (let i = 0; i < 5; i++) {
      await page.click('#new-chat-btn');
      await page.fill('#message-input', `Conversation ${i + 2}`);
      await page.click('#send-btn');
      // Wait for the assistant response in this new conversation (nth=0 since messages are cleared)
      await page.waitForSelector('.message.assistant', { timeout: 10000 });
    }

    // Navigate directly to the first conversation via URL
    await page.goto(`/#/conversations/${firstConvId}`);
    await page.waitForSelector('#new-chat-btn');

    // Should load the first conversation
    const userMessage = page.locator('.message.user');
    await expect(userMessage).toBeVisible({ timeout: 10000 });
    await expect(userMessage).toContainText('First message for deep link test');

    // The conversation should be added to the sidebar
    const convItem = page.locator(`.conversation-item-wrapper[data-conv-id="${firstConvId}"]`);
    await expect(convItem).toBeVisible();

    // It should be marked as active
    await expect(convItem).toHaveClass(/active/);
  });
});

test.describe('Deep Linking - Edge Cases', () => {
  test('handles temp conversation ID in URL gracefully', async ({ page }) => {
    // Navigate to a temp conversation (should be ignored)
    await page.goto('/#/conversations/temp-12345678');
    await page.waitForSelector('#new-chat-btn');

    // Should treat as home (no conversation selected)
    const welcomeMessage = page.locator('.welcome-message');
    await expect(welcomeMessage).toBeVisible();

    // Hash should be cleared
    const hash = await page.evaluate(() => window.location.hash);
    expect(hash).toBe('');
  });

  test('handles malformed hash gracefully', async ({ page }) => {
    // Navigate to a malformed hash
    await page.goto('/#/invalid/path/here');
    await page.waitForSelector('#new-chat-btn');

    // Should treat as home
    const hash = await page.evaluate(() => window.location.hash);
    expect(hash).toBe('#/invalid/path/here'); // Hash remains but no action taken

    // No error should be shown, just home view
    const messagesContainer = page.locator('#messages');
    await expect(messagesContainer).toBeVisible();
  });

  test('handles empty hash', async ({ page }) => {
    // Navigate with empty hash
    await page.goto('/#');
    await page.waitForSelector('#new-chat-btn');

    // Should show home view
    const welcomeMessage = page.locator('.welcome-message');
    // Welcome message shows if no conversation is selected
    // But we might have conversations from previous tests in the sidebar
    // so just check we don't have an error
    const toasts = page.locator('.toast-error');
    await expect(toasts).toHaveCount(0);
  });

  test('preserves hash after page refresh', async ({ page }) => {
    // Navigate to home first
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Disable streaming
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    if (isPressed === 'true') {
      await streamBtn.click();
    }

    // Create a conversation
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test for hash preservation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    const originalHash = await page.evaluate(() => window.location.hash);
    expect(originalHash).toMatch(/^#\/conversations\/[a-zA-Z0-9-]+$/);

    // Refresh the page
    await page.reload();
    await page.waitForSelector('#new-chat-btn');

    // Hash should be preserved
    const hashAfterRefresh = await page.evaluate(() => window.location.hash);
    expect(hashAfterRefresh).toBe(originalHash);

    // Conversation should be loaded
    const userMessage = page.locator('.message.user');
    await expect(userMessage).toBeVisible({ timeout: 10000 });
    await expect(userMessage).toContainText('Test for hash preservation');
  });
});

