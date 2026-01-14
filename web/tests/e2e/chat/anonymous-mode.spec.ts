/**
 * E2E tests for anonymous mode functionality
 */
import { test, expect, setMockResponse } from './fixtures';

test.describe('Chat - Anonymous Mode', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');
  });

  test('anonymous button is visible', async ({ page }) => {
    const anonymousBtn = page.locator('#anonymous-btn');
    await expect(anonymousBtn).toBeVisible();
  });

  test('anonymous button toggles active state', async ({ page }) => {
    const anonymousBtn = page.locator('#anonymous-btn');

    // Initially not active
    await expect(anonymousBtn).not.toHaveClass(/active/);

    // Click to activate
    await anonymousBtn.click();
    await expect(anonymousBtn).toHaveClass(/active/);

    // Click to deactivate
    await anonymousBtn.click();
    await expect(anonymousBtn).not.toHaveClass(/active/);
  });

  test('anonymous toggle state persists across messages (unlike force tools)', async ({ page }) => {
    const anonymousBtn = page.locator('#anonymous-btn');

    // Activate anonymous mode
    await anonymousBtn.click();
    await expect(anonymousBtn).toHaveClass(/active/);

    // Send message
    await page.fill('#message-input', 'Test message');
    await page.click('#send-btn');

    // Wait for response
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Anonymous button should STILL be active (persists, unlike force tools)
    await expect(anonymousBtn).toHaveClass(/active/);

    // Send another message
    await page.fill('#message-input', 'Another test message');
    await page.click('#send-btn');

    // Wait for second response
    await page.locator('.message.assistant').nth(1).waitFor({ timeout: 10000 });

    // Anonymous button should still be active
    await expect(anonymousBtn).toHaveClass(/active/);
  });

  test('anonymous toggle state resets on new conversation (defaults to off)', async ({ page }) => {
    const anonymousBtn = page.locator('#anonymous-btn');

    // Activate anonymous mode
    await anonymousBtn.click();
    await expect(anonymousBtn).toHaveClass(/active/);

    // Send message to persist the conversation
    await page.fill('#message-input', 'Test message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Create new conversation
    await page.click('#new-chat-btn');

    // Anonymous mode should be OFF by default for new conversations
    await expect(anonymousBtn).not.toHaveClass(/active/);
  });

  test('anonymous toggle state is independent per conversation', async ({ page }) => {
    const anonymousBtn = page.locator('#anonymous-btn');

    // Activate anonymous mode in first conversation
    await anonymousBtn.click();
    await expect(anonymousBtn).toHaveClass(/active/);

    // Send message to persist the conversation
    await page.fill('#message-input', 'First conversation message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Create second conversation (should be non-anonymous by default)
    await page.click('#new-chat-btn');
    await expect(anonymousBtn).not.toHaveClass(/active/);

    // Send message in second conversation (non-anonymous)
    await page.fill('#message-input', 'Second conversation message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Now we should have 2 conversations
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(2);

    // Switch back to first conversation - should restore anonymous state
    await convItems.last().click();
    await expect(anonymousBtn).toHaveClass(/active/);

    // Switch to second conversation - should be non-anonymous
    await convItems.first().click();
    await expect(anonymousBtn).not.toHaveClass(/active/);
  });

  test('anonymous mode persists through temp-to-permanent conversation transition (regression)', async ({
    page,
  }) => {
    // This test covers the bug where anonymous mode was lost when a temp conversation
    // was persisted to the backend on the first message send.
    // The anonymous state was stored under temp-xxx ID but the message was sent
    // using the new real-yyy ID, causing anonymous_mode=false to be sent.

    const anonymousBtn = page.locator('#anonymous-btn');

    // Step 1: Enable anonymous mode in the NEW (temp) conversation
    await anonymousBtn.click();
    await expect(anonymousBtn).toHaveClass(/active/);

    // Step 2: Verify we're in a temp conversation (no real ID yet)
    // The URL hash should be empty or not have a conversation ID
    const urlBeforeSend = new URL(page.url());
    expect(urlBeforeSend.hash).toBe('');

    // Step 3: Send a message - this triggers temp->permanent ID conversion
    // Set a custom mock response to verify anonymous mode is working
    await setMockResponse(page, 'Anonymous mode is working correctly!');

    await page.fill('#message-input', 'Test anonymous mode in new conversation');
    await page.click('#send-btn');

    // Wait for response
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Step 4: Verify the anonymous button is still active after the temp->permanent transition
    await expect(anonymousBtn).toHaveClass(/active/);

    // Step 5: Verify the conversation now has a real ID in the URL
    const urlAfterSend = new URL(page.url());
    expect(urlAfterSend.hash).toMatch(/#\/conversations\/[a-f0-9-]+/);

    // Step 6: Send another message - should still be anonymous
    await page.fill('#message-input', 'Second message still anonymous');
    await page.click('#send-btn');

    // Wait for second response
    await page.locator('.message.assistant').nth(1).waitFor({ timeout: 10000 });

    // Anonymous mode should persist
    await expect(anonymousBtn).toHaveClass(/active/);
  });
});

/**
 * Anonymous Mode - Initial State Tests
 *
 * These tests verify anonymous mode behavior on initial page load WITHOUT
 * clicking "New Chat" first. This is a separate describe block without
 * beforeEach to test the true initial state.
 */
test.describe('Chat - Anonymous Mode Initial State', () => {
  test('anonymous mode works on initial page load without clicking new chat (regression)', async ({
    page,
  }) => {
    // This test covers the bug where anonymous mode did not work on initial page load.
    // The issue was that when the page loads without a deeplink, there's no current
    // conversation, and clicking the anonymous button did nothing because the click
    // handler early-returned when convId was null.
    // The fix uses pendingAnonymousMode state (similar to pendingModel) that gets
    // applied when a conversation is created.

    // Step 1: Go to root WITHOUT clicking new-chat-btn (fresh page state)
    await page.goto('/');
    await page.waitForSelector('#anonymous-btn');

    // Step 2: Verify there's no current conversation (no hash in URL)
    const urlBefore = new URL(page.url());
    expect(urlBefore.hash).toBe('');

    // Step 3: Click anonymous mode button - should work even without a conversation
    const anonymousBtn = page.locator('#anonymous-btn');
    await expect(anonymousBtn).not.toHaveClass(/active/);
    await anonymousBtn.click();
    await expect(anonymousBtn).toHaveClass(/active/);

    // Step 4: Send a message - this should create a conversation with anonymous mode ON
    await page.request.post('/test/set-mock-response', {
      data: { response: 'Anonymous mode activated on initial load!' },
    });

    await page.fill('#message-input', 'Test anonymous mode on initial load');
    await page.click('#send-btn');

    // Wait for response
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Step 5: Verify anonymous button is still active
    await expect(anonymousBtn).toHaveClass(/active/);

    // Step 6: Verify we now have a conversation with a real ID
    const urlAfter = new URL(page.url());
    expect(urlAfter.hash).toMatch(/#\/conversations\/[a-f0-9-]+/);
  });

  test('pending anonymous mode is cleared when creating new conversation', async ({ page }) => {
    // This test ensures that when a user:
    // 1. Enables anonymous mode without a conversation
    // 2. The pending state is applied to the new conversation
    // 3. The pending state is cleared after being applied
    // So that subsequent new conversations default to non-anonymous

    // Step 1: Go to root (no conversation)
    await page.goto('/');
    await page.waitForSelector('#anonymous-btn');

    // Step 2: Enable anonymous mode in "pending" state
    const anonymousBtn = page.locator('#anonymous-btn');
    await anonymousBtn.click();
    await expect(anonymousBtn).toHaveClass(/active/);

    // Step 3: Click new-chat-btn - this creates conversation and consumes pending state
    await page.click('#new-chat-btn');

    // Anonymous mode should be active (pending state was applied)
    await expect(anonymousBtn).toHaveClass(/active/);

    // Step 4: Send a message to persist the conversation
    await page.fill('#message-input', 'First conversation');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Step 5: Click new-chat-btn AGAIN - this new conversation should be NON-anonymous
    // because pending state was cleared when first conversation was created
    await page.click('#new-chat-btn');
    await expect(anonymousBtn).not.toHaveClass(/active/);
  });
});
