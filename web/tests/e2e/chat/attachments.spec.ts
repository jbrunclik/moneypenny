/**
 * E2E tests for file attachments, image loading scroll, and upload progress
 */
import {
  test,
  expect,
  pngBase64,
  disableStreaming,
  setBatchDelay,
  resetBatchDelay,
} from './fixtures';
import { Buffer } from 'buffer';

test.describe('Chat - Image Loading Scroll', () => {
  /**
   * REGRESSION TEST: Image at top of conversation causing scroll issues
   *
   * Bug: When loading a conversation with an image at the TOP (above viewport),
   * the image loading would increase scrollHeight, making it appear the user
   * had scrolled away from the bottom. The position-based scroll listener
   * would then disable auto-scroll before the final smooth scroll could run.
   *
   * Fix: Changed setupUserScrollListener to use direction-based detection
   * (like streaming scroll listener). Only disables scroll mode when scrollTop
   * DECREASES (user actually scrolled up), not when distanceFromBottom increases
   * due to images loading above viewport.
   */
  test('scrolls to bottom when conversation has image at top', async ({ page }) => {
    // Create a conversation with many messages and an image in the first message
    // The image will be above the viewport when we scroll to bottom

    // Create messages: first one has an image, then several text messages
    const messages = [
      {
        role: 'user',
        content: 'Here is an image',
        files: [
          {
            name: 'test-image.png',
            type: 'image/png',
            data: pngBase64,
          },
        ],
      },
      { role: 'assistant', content: 'I see the image you shared.' },
    ];

    // Add more messages to ensure the image is above the viewport
    for (let i = 0; i < 10; i++) {
      messages.push({ role: 'user', content: `Follow-up message ${i + 1}` });
      messages.push({
        role: 'assistant',
        content: `This is a response to follow-up ${i + 1}. It has some content to take up space.`,
      });
    }

    // Seed the conversation via test API
    const response = await page.request.post('/test/seed', {
      data: {
        conversations: [{ title: 'Image at Top Test', messages }],
      },
    });
    expect(response.ok()).toBe(true);

    // Navigate to the app
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Click on the seeded conversation
    const conversationItem = page.locator('.conversation-item-wrapper').first();
    await expect(conversationItem).toBeVisible({ timeout: 5000 });
    await conversationItem.click();

    // Wait for messages to load
    await page.waitForSelector('.message.user', { timeout: 10000 });

    // Wait for image to load (this is the key part of the test)
    // The image loading above viewport should not prevent final scroll
    const messageImage = page.locator('.message-image');
    await expect(messageImage).toBeVisible({ timeout: 10000 });

    // Wait a bit for scroll logic to complete
    await page.waitForTimeout(500);

    // Verify we're at the bottom after everything loads
    const messagesContainer = page.locator('#messages');
    const scrollInfo = await messagesContainer.evaluate((el) => ({
      scrollTop: el.scrollTop,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    }));
    const distanceFromBottom =
      scrollInfo.scrollHeight - scrollInfo.scrollTop - scrollInfo.clientHeight;

    // Should be at or very near the bottom (within threshold)
    // Using a reasonable threshold since smooth scroll may not be pixel-perfect
    expect(distanceFromBottom).toBeLessThan(50);
  });

  test('user can still scroll up to disable auto-scroll with images', async ({ page }) => {
    // Create a conversation with an image and enough content to scroll

    const messages = [
      {
        role: 'user',
        content: 'Here is an image',
        files: [{ name: 'test.png', type: 'image/png', data: pngBase64 }],
      },
      { role: 'assistant', content: 'I see the image.' },
    ];

    for (let i = 0; i < 10; i++) {
      messages.push({ role: 'user', content: `Message ${i + 1}` });
      messages.push({ role: 'assistant', content: `Response ${i + 1} with content.` });
    }

    await page.request.post('/test/seed', {
      data: { conversations: [{ title: 'User Scroll Test', messages }] },
    });

    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    const conversationItem = page.locator('.conversation-item-wrapper').first();
    await conversationItem.click();

    await page.waitForSelector('.message.user', { timeout: 10000 });

    // Wait for all images to load completely
    const images = page.locator('.message-image');
    const imageCount = await images.count();
    for (let i = 0; i < imageCount; i++) {
      await images.nth(i).evaluate((img: HTMLImageElement) => {
        return new Promise<void>((resolve) => {
          if (img.complete) {
            resolve();
          } else {
            img.onload = () => resolve();
            img.onerror = () => resolve();
          }
        });
      });
    }

    const messagesContainer = page.locator('#messages');

    // Wait for initial scroll to bottom and any pending scroll operations to complete
    // Use longer timeout for webkit which can be slower with scroll timing
    await page.waitForTimeout(1500);

    // Verify we're at the bottom first
    const initialScrollInfo = await messagesContainer.evaluate((el) => ({
      scrollTop: el.scrollTop,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    }));
    const initialDistanceFromBottom =
      initialScrollInfo.scrollHeight - initialScrollInfo.scrollTop - initialScrollInfo.clientHeight;
    expect(initialDistanceFromBottom).toBeLessThan(100); // Should be at bottom initially

    // Scroll up (this should disable auto-scroll)
    await messagesContainer.evaluate((el) => {
      el.scrollTo({ top: 0, behavior: 'instant' });
    });

    // Wait for scroll event to be processed - webkit needs more time
    await page.waitForTimeout(1000);

    // Verify we're still at the top (not scrolled back to bottom)
    const scrollTop = await messagesContainer.evaluate((el) => el.scrollTop);
    expect(scrollTop).toBeLessThan(50); // Allow some tolerance

    // If we stayed at top, auto-scroll was correctly disabled
    // (If the bug existed, we would have been scrolled back to bottom)
  });
});

test.describe('Chat - Upload Progress', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');
  });

  test('upload progress element exists and is initially hidden', async ({ page }) => {
    const uploadProgress = page.locator('#upload-progress');

    // Upload progress should exist in the DOM
    await expect(uploadProgress).toBeAttached();

    // Upload progress should be hidden initially
    await expect(uploadProgress).toHaveClass(/hidden/);

    // Should have progress bar and text elements
    const progressBar = uploadProgress.locator('.upload-progress-bar');
    const progressText = uploadProgress.locator('.upload-progress-text');
    await expect(progressBar).toBeAttached();
    await expect(progressText).toBeAttached();
  });

  test('upload progress shows briefly when sending message with files', async ({ page }) => {
    const uploadProgress = page.locator('#upload-progress');

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

    // Verify file preview is shown
    const filePreview = page.locator('#file-preview');
    await expect(filePreview).not.toHaveClass(/hidden/, { timeout: 3000 });

    // Add a batch delay to slow down the response so we can observe the progress
    await setBatchDelay(page, 1000);

    // Set up a MutationObserver before clicking send to catch the progress indicator
    const progressWasShown = page.evaluate(() => {
      return new Promise<boolean>((resolve) => {
        const uploadEl = document.getElementById('upload-progress');
        if (!uploadEl) {
          resolve(false);
          return;
        }

        // If already visible, we caught it
        if (!uploadEl.classList.contains('hidden')) {
          resolve(true);
          return;
        }

        // Watch for the hidden class to be removed
        const observer = new MutationObserver((mutations) => {
          for (const mutation of mutations) {
            if (
              mutation.type === 'attributes' &&
              mutation.attributeName === 'class' &&
              !uploadEl.classList.contains('hidden')
            ) {
              observer.disconnect();
              resolve(true);
              return;
            }
          }
        });

        observer.observe(uploadEl, { attributes: true, attributeFilter: ['class'] });

        // Timeout after 5 seconds
        setTimeout(() => {
          observer.disconnect();
          resolve(false);
        }, 5000);
      });
    });

    // Click send to start the upload
    await page.click('#send-btn');

    // Check if progress was shown during the request
    const wasShown = await progressWasShown;
    expect(wasShown).toBe(true);

    // Wait for the message to complete
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });

    // Progress should be hidden after completion
    await expect(uploadProgress).toHaveClass(/hidden/);

    // Reset batch delay
    await resetBatchDelay(page);
  });

  test('upload progress is hidden after completion', async ({ page }) => {
    const uploadProgress = page.locator('#upload-progress');

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

    // Send the message
    await page.click('#send-btn');

    // Wait for the message to complete
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });

    // Progress should be hidden after completion
    await expect(uploadProgress).toHaveClass(/hidden/);
  });
});
