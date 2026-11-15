/**
 * Input gestures for E2E specs that need a browser quirk worked around.
 */
import type { Page } from '@playwright/test';

/**
 * Wheel-scroll the message list by `deltaY` (negative = up).
 *
 * macOS WebKit under Playwright 1.65 drops a synthetic wheel unless the
 * document has a wheel listener (one on the list itself is not enough): the
 * list never moves. Linux WebKit and real Safari scroll without one, so a
 * no-op passive listener is installed first - it changes nothing else.
 */
export async function wheelMessages(page: Page, deltaY: number): Promise<void> {
  await page.evaluate(() => document.addEventListener('wheel', () => {}, { passive: true }));
  await page.locator('#messages').hover();
  await page.mouse.wheel(0, deltaY);
}
