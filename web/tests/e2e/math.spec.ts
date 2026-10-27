import { test, expect } from '../global-setup';
import { appReady } from './waits';

const WIDE_EQUATION =
  'Start at 3:\n\n$$\\pi = 3 + \\frac{4}{2 \\cdot 3 \\cdot 4} - \\frac{4}{4 \\cdot 5 \\cdot 6} + \\frac{4}{6 \\cdot 7 \\cdot 8} - \\frac{4}{8 \\cdot 9 \\cdot 10} + \\frac{4}{10 \\cdot 11 \\cdot 12} - \\dots$$\n\nDone.';

test.describe('Math', () => {
  test('wide display math scrolls sideways on mobile instead of being cut off', async ({ page, request }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await request.post('/test/set-mock-response', { data: { response: WIDE_EQUATION } });
    await page.goto('/');
    await appReady(page);
    if (await page.locator('#menu-btn').isVisible()) await page.click('#menu-btn');
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Leibniz-like series for pi');
    await page.click('#send-btn');

    const display = page.locator('.message.assistant:not(.streaming) .katex-display');
    await expect(display).toBeVisible({ timeout: 15000 });

    const box = (await display.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(390);
    const scrolled = await display.evaluate((el) => {
      el.scrollLeft = el.scrollWidth;
      return { overflows: el.scrollWidth > el.clientWidth, scrollLeft: el.scrollLeft };
    });
    expect(scrolled.overflows).toBe(true);
    expect(scrolled.scrollLeft).toBeGreaterThan(0);
  });
});
