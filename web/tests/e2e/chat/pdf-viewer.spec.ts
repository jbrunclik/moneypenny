/**
 * E2E tests for the inline PDF viewer (clicking a PDF attachment renders
 * it in the overlay instead of window.open).
 */
import type { Locator, Page } from '@playwright/test';
import { test, expect, pdfBuffer, disableStreaming } from './fixtures';

const PDF_VIEWER_CHUNK = 'PdfViewer-*.js';

/**
 * Delete a build file the way a deploy does: the server answers 404 for it,
 * as in production, instead of a page.route intercept on the chunk loads
 * around the reload. page.request carries the test's X-Test-Execution-Id.
 */
async function deleteChunk(page: Page, pattern: string): Promise<void> {
  const response = await page.request.post('/test/set-missing-assets', { data: { patterns: [pattern] } });
  expect(response.ok()).toBeTruthy();
}


/** Send a message with a PDF attached; returns the document link in the user bubble. */
async function sendPdf(page: Page): Promise<Locator> {
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

  // The document name in the user message
  const docLink = page.locator('.message.user .document-preview');
  await expect(docLink).toBeVisible({ timeout: 5000 });
  return docLink;
}

/** Mark the current page so a reload is detectable (the marker does not survive one). */
async function markPage(page: Page): Promise<void> {
  await page.evaluate(() => {
    (window as Window & { __beforeReload?: boolean }).__beforeReload = true;
  });
}

async function pageWasReloaded(page: Page): Promise<boolean> {
  return page.evaluate(() => !(window as Window & { __beforeReload?: boolean }).__beforeReload);
}

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
    const docLink = await sendPdf(page);
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

  // The reloaded page running the new build is not covered here: in production
  // it asks for the new build's filename, while a test can only re-request the
  // same URL, whose failed load WebKit reuses without asking the network again
  test('a chunk deleted by a deploy reloads the page', async ({ page }) => {
    const docLink = await sendPdf(page);

    // A page loaded before a deploy asks for the previous build's chunk, which
    // the rebuild deleted: the server answers 404
    await deleteChunk(page, PDF_VIEWER_CHUNK);
    await markPage(page);
    // The reload replaces the failure: nothing reaches the page as an error
    const errors: Error[] = [];
    page.on('pageerror', (error) => errors.push(error));
    const reloaded = page.waitForEvent('load');
    await docLink.click();
    await reloaded;
    expect(await pageWasReloaded(page)).toBe(true);
    expect(errors.map((error) => error.message)).toEqual([]);
    await expect(page.locator('.message.user .document-preview')).toBeVisible({ timeout: 10000 });
  });

  test('a chunk that still fails right after the reload does not reload again', async ({
    page,
  }) => {
    const docLink = await sendPdf(page);
    await deleteChunk(page, PDF_VIEWER_CHUNK);
    const reloaded = page.waitForEvent('load');
    await docLink.click();
    await reloaded;

    // Still failing after the reload (a real outage, not a stale page): the
    // error surfaces instead of another reload
    await markPage(page);
    const failure = page.waitForEvent('pageerror');
    await page.locator('.message.user .document-preview').click();
    // The chunk's own load failure, not a follow-on error in the click handler
    expect((await failure).message).toMatch(/dynamically imported module|Importing a module script failed/);
    await page.waitForTimeout(1000);
    expect(await pageWasReloaded(page)).toBe(false);
  });
});
