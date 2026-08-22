/**
 * E2E tests for the inline PDF viewer (clicking a PDF attachment renders
 * it in the overlay instead of window.open).
 */
import { test, expect, pdfBuffer, disableStreaming } from './fixtures';

test.describe('Chat - Inline PDF viewer', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');
    await disableStreaming(page);
  });

  test('clicking a PDF attachment opens the inline viewer with rendered pages', async ({
    page,
  }) => {
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('#attach-btn');
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles({
      name: 'hello.pdf',
      mimeType: 'application/pdf',
      buffer: pdfBuffer,
    });

    const filePreview = page.locator('#file-preview');
    await expect(filePreview).not.toHaveClass(/hidden/, { timeout: 3000 });

    await page.fill('#message-input', 'Here is a PDF');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Click the document name in the user message
    const docLink = page.locator('.message.user .document-preview');
    await expect(docLink).toBeVisible({ timeout: 5000 });
    await docLink.click();

    // Inline viewer opens with the filename and a rendered page canvas
    const overlay = page.locator('.pdf-viewer-overlay');
    await expect(overlay).toBeVisible({ timeout: 10000 });
    await expect(overlay.locator('.pdf-viewer-title')).toHaveText('hello.pdf');
    await expect(overlay.locator('canvas.pdf-viewer-page')).toHaveCount(1, { timeout: 15000 });
    await expect(overlay.locator('.pdf-viewer-pages')).toHaveText('1 page');

    // No pop-up/new tab involved and no error toast
    await expect(page.locator('.toast.error')).toHaveCount(0);

    // Escape closes the viewer
    await page.keyboard.press('Escape');
    await expect(overlay).toHaveCount(0);
  });
});
