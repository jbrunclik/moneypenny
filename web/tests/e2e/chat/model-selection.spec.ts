/**
 * E2E tests for model selection and persistence
 */
import { test, expect, enableStreaming, disableStreaming } from './fixtures';

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

    // Get initial model short name (shown in button)
    const initialModelShortName = await page.locator('#current-model-name').textContent();

    // Open dropdown
    await modelSelectorBtn.click();
    await expect(modelDropdown).not.toHaveClass(/hidden/);

    // Get all model options
    const modelOptions = modelDropdown.locator('.model-option');
    const optionCount = await modelOptions.count();
    expect(optionCount).toBeGreaterThan(1); // Ensure we have multiple models to choose from

    // Find a model that is NOT currently selected (no .selected class)
    let differentModelOption = null;
    let differentModelShortName = null;
    for (let i = 0; i < optionCount; i++) {
      const option = modelOptions.nth(i);
      const isSelected = await option.evaluate((el) => el.classList.contains('selected'));
      if (!isSelected) {
        differentModelOption = option;
        // Get short name from data attribute (button shows short name, not full name)
        differentModelShortName = await option.getAttribute('data-short-name');
        break;
      }
    }

    // Ensure we found a different model
    expect(differentModelOption).not.toBeNull();
    expect(differentModelShortName).not.toBe(initialModelShortName);

    // Click on the different model
    await differentModelOption!.click();

    // Dropdown should close
    await expect(modelDropdown).toHaveClass(/hidden/);

    // Model name should be updated in the button (shows short name)
    const newModelShortName = await page.locator('#current-model-name').textContent();
    expect(newModelShortName).toBe(differentModelShortName);

    // No error toast should appear (this was the bug)
    // Toast has class "toast toast-error" for error type
    const errorToast = page.locator('.toast-error');
    // Use a short timeout since we're asserting absence
    await expect(errorToast).toHaveCount(0, { timeout: 200 });

    // Now send a message - the conversation should be created with the selected model
    // Disable streaming for reliable response
    await disableStreaming(page);

    await page.fill('#message-input', 'Test with selected model');
    await page.click('#send-btn');

    // Wait for response
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // The model should still be the one we selected (short name in button)
    const finalModelShortName = await page.locator('#current-model-name').textContent();
    expect(finalModelShortName).toBe(differentModelShortName);
  });

  test('model selection persists after sending first message', async ({ page }) => {
    const modelSelectorBtn = page.locator('#model-selector-btn');
    const modelDropdown = page.locator('#model-dropdown');

    // Disable streaming for reliable response
    await disableStreaming(page);

    // Open dropdown and select a non-default model
    await modelSelectorBtn.click();
    await expect(modelDropdown).not.toHaveClass(/hidden/);

    // Get all model options and find one that's not selected
    const modelOptions = modelDropdown.locator('.model-option');
    let targetOption = null;
    let targetModelShortName = null;
    const optionCount = await modelOptions.count();
    for (let i = 0; i < optionCount; i++) {
      const option = modelOptions.nth(i);
      const isSelected = await option.evaluate((el) => el.classList.contains('selected'));
      if (!isSelected) {
        targetOption = option;
        // Get short name from data attribute (button shows short name, not full name)
        targetModelShortName = await option.getAttribute('data-short-name');
        break;
      }
    }

    expect(targetOption).not.toBeNull();
    await targetOption!.click();

    // Verify model is selected (button shows short name)
    const selectedModelShortName = await page.locator('#current-model-name').textContent();
    expect(selectedModelShortName).toBe(targetModelShortName);

    // Send first message (this persists the conversation)
    await page.fill('#message-input', 'First message with selected model');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Model should still be the one we selected (short name in button)
    expect(await page.locator('#current-model-name').textContent()).toBe(targetModelShortName);

    // Switch to another conversation and back
    await page.click('#new-chat-btn');

    // Switch back to the original conversation
    const convItems = page.locator('.conversation-item-wrapper');
    await expect(convItems).toHaveCount(2);
    await convItems.last().click(); // Original conversation

    // Wait for conversation to load
    await page.waitForSelector('.message.user', { timeout: 10000 });

    // Model should still be the one we selected for this conversation (short name)
    expect(await page.locator('#current-model-name').textContent()).toBe(targetModelShortName);
  });

  test('model selection persists after sending first message in streaming mode', async ({
    page,
  }) => {
    const modelSelectorBtn = page.locator('#model-selector-btn');
    const modelDropdown = page.locator('#model-dropdown');

    // Enable streaming
    await enableStreaming(page);

    // Open dropdown and select a non-default model
    await modelSelectorBtn.click();
    await expect(modelDropdown).not.toHaveClass(/hidden/);

    // Get all model options and find one that's not selected
    const modelOptions = modelDropdown.locator('.model-option');
    let targetOption = null;
    let targetModelShortName = null;
    const optionCount = await modelOptions.count();
    for (let i = 0; i < optionCount; i++) {
      const option = modelOptions.nth(i);
      const isSelected = await option.evaluate((el) => el.classList.contains('selected'));
      if (!isSelected) {
        targetOption = option;
        // Get short name from data attribute (button shows short name, not full name)
        targetModelShortName = await option.getAttribute('data-short-name');
        break;
      }
    }

    expect(targetOption).not.toBeNull();
    await targetOption!.click();

    // Verify model is selected (button shows short name)
    const selectedModelShortName = await page.locator('#current-model-name').textContent();
    expect(selectedModelShortName).toBe(targetModelShortName);

    // Send first message (this persists the conversation)
    await page.fill('#message-input', 'First message with selected model (streaming)');
    await page.click('#send-btn');

    // Wait for streaming to complete
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toContainText('mock response', { timeout: 10000 });

    // Model should still be the one we selected (short name in button)
    expect(await page.locator('#current-model-name').textContent()).toBe(targetModelShortName);
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

    // Get initial model short name (shown in button)
    const initialModelShortName = await page.locator('#current-model-name').textContent();

    // Open dropdown
    await modelSelectorBtn.click();
    await expect(modelDropdown).not.toHaveClass(/hidden/);

    // Find a model that is NOT currently selected
    const modelOptions = modelDropdown.locator('.model-option');
    let differentModelOption = null;
    let differentModelShortName = null;
    let differentModelId = null;
    const optionCount = await modelOptions.count();
    for (let i = 0; i < optionCount; i++) {
      const option = modelOptions.nth(i);
      const isSelected = await option.evaluate((el) => el.classList.contains('selected'));
      if (!isSelected) {
        differentModelOption = option;
        // Get short name from data attribute (button shows short name, not full name)
        differentModelShortName = await option.getAttribute('data-short-name');
        differentModelId = await option.getAttribute('data-model-id');
        break;
      }
    }

    expect(differentModelOption).not.toBeNull();
    expect(differentModelShortName).not.toBe(initialModelShortName);

    // Select the different model
    await differentModelOption!.click();
    await expect(modelDropdown).toHaveClass(/hidden/);

    // Model short name should be updated in the button
    const newModelShortName = await page.locator('#current-model-name').textContent();
    expect(newModelShortName).toBe(differentModelShortName);

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

    // Model should still be the one we selected (short name in button)
    expect(await page.locator('#current-model-name').textContent()).toBe(differentModelShortName);

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
