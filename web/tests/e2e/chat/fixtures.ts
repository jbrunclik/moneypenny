/**
 * Shared fixtures and utilities for chat E2E tests
 */
import { test as base, expect, Page } from '../../global-setup';
import { Buffer } from 'buffer';

/**
 * Valid PNG buffer (8x8 red image) for file upload tests
 */
export const pngBuffer = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAADklEQVQI12P4z8DAwMAAAx4D/dnaJvgAAAAASUVORK5CYII=',
  'base64'
);

/**
 * Minimal 1x1 transparent PNG for lightweight tests
 */
export const pngBase64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';

/**
 * Create a new chat and optionally configure streaming mode
 */
export async function setupNewChat(
  page: Page,
  options: { streaming?: boolean } = {}
): Promise<void> {
  await page.goto('/');
  await page.waitForSelector('#new-chat-btn');
  await page.click('#new-chat-btn');

  if (options.streaming !== undefined) {
    const streamBtn = page.locator('#stream-btn');
    const isPressed = await streamBtn.getAttribute('aria-pressed');
    const isCurrentlyStreaming = isPressed === 'true';

    if (options.streaming !== isCurrentlyStreaming) {
      await streamBtn.click();
    }
  }
}

/**
 * Enable streaming mode
 */
export async function enableStreaming(page: Page): Promise<void> {
  const streamBtn = page.locator('#stream-btn');
  const isPressed = await streamBtn.getAttribute('aria-pressed');
  if (isPressed !== 'true') {
    await streamBtn.click();
  }
}

/**
 * Disable streaming mode
 */
export async function disableStreaming(page: Page): Promise<void> {
  const streamBtn = page.locator('#stream-btn');
  const isPressed = await streamBtn.getAttribute('aria-pressed');
  if (isPressed === 'true') {
    await streamBtn.click();
  }
}

/**
 * Send a message and wait for assistant response
 */
export async function sendMessageAndWait(
  page: Page,
  message: string,
  timeout = 10000
): Promise<void> {
  await page.fill('#message-input', message);
  await page.click('#send-btn');
  await page.waitForSelector('.message.assistant', { timeout });
}

/**
 * Upload a test image via the attach button
 */
export async function uploadTestImage(
  page: Page,
  fileName = 'test-image.png'
): Promise<void> {
  const fileChooserPromise = page.waitForEvent('filechooser');
  await page.click('#attach-btn');
  const fileChooser = await fileChooserPromise;

  await fileChooser.setFiles({
    name: fileName,
    mimeType: 'image/png',
    buffer: Buffer.from(pngBase64, 'base64'),
  });
}

/**
 * Wait for file preview to be visible
 */
export async function waitForFilePreview(page: Page, timeout = 3000): Promise<void> {
  const filePreview = page.locator('#file-preview');
  await expect(filePreview).not.toHaveClass(/hidden/, { timeout });
}

/**
 * Set stream delay for tests
 */
export async function setStreamDelay(page: Page, delayMs: number): Promise<void> {
  await page.request.post('/test/set-stream-delay', { data: { delay_ms: delayMs } });
}

/**
 * Reset stream delay to default
 */
export async function resetStreamDelay(page: Page): Promise<void> {
  await page.request.post('/test/set-stream-delay', { data: { delay_ms: 10 } });
}

/**
 * Set batch delay for tests
 */
export async function setBatchDelay(page: Page, delayMs: number): Promise<void> {
  await page.request.post('/test/set-batch-delay', { data: { delay_ms: delayMs } });
}

/**
 * Reset batch delay to default
 */
export async function resetBatchDelay(page: Page): Promise<void> {
  await page.request.post('/test/set-batch-delay', { data: { delay_ms: 0 } });
}

/**
 * Set custom mock response
 */
export async function setMockResponse(page: Page, response: string): Promise<void> {
  await page.request.post('/test/set-mock-response', { data: { response } });
}

/**
 * Clear mock response
 */
export async function clearMockResponse(page: Page): Promise<void> {
  await page.request.post('/test/clear-mock-response');
}

/**
 * Enable/disable thinking events
 */
export async function setEmitThinking(page: Page, emit: boolean): Promise<void> {
  await page.request.post('/test/set-emit-thinking', { data: { emit } });
}

// Re-export test and expect from global-setup
export { test, expect } from '../../global-setup';
