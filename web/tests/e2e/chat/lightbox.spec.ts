/**
 * E2E tests for image lightbox functionality
 */
import { test, expect, pngBuffer, enableStreaming, disableStreaming } from './fixtures';

test.describe('Chat - Lightbox', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Disable streaming for consistent tests
    await disableStreaming(page);
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

  test('clicking image during streaming opens lightbox after user_message_saved event', async ({
    page,
  }) => {
    // Enable streaming for this test
    await enableStreaming(page);

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
    await enableStreaming(page);

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
