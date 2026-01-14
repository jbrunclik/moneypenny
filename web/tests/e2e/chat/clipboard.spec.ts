/**
 * E2E tests for clipboard paste and copy functionality
 */
import {
  test,
  expect,
  pngBase64,
  disableStreaming,
  setMockResponse,
  clearMockResponse,
} from './fixtures';
import { Buffer } from 'buffer';

test.describe('Chat - Clipboard Paste', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');
  });

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
    await disableStreaming(page);
  });

  test.afterEach(async ({ page }) => {
    // Always clean up mock response after each test
    await clearMockResponse(page);
  });

  test('shows inline copy button on code blocks', async ({ page }) => {
    // Set a response with a code block
    await setMockResponse(page, '```python\nprint("Hello World")\n```');

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
    await setMockResponse(page, '| Name | Age |\n|------|-----|\n| Alice | 30 |\n| Bob | 25 |');

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
    await setMockResponse(page, '```javascript\nconsole.log("test");\n```');

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
    await setMockResponse(page, 'Here is some code:\n\n```python\nprint("test")\n```');

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
    await setMockResponse(page, '```python\nprint("Hello")\n```');

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
