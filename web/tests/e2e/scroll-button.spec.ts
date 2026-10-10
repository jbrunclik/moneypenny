/**
 * The scroll-to-bottom button: one tap lands at the bottom.
 *
 * It used to stop at the height seen on its last animation frame, so content
 * landing at the end (a diagram rendering, the actions row, an image) left the
 * list short and the button still showing - "needs multiple taps".
 */
import { test, expect } from '../global-setup';

test.use({ viewport: { width: 390, height: 664 }, hasTouch: true });

test('one tap reaches the bottom even when content grows during the scroll', async ({ page, request }) => {
  const messages = Array.from({ length: 40 }, (_, i) => ({
    role: i % 2 ? 'assistant' : 'user',
    content: `Message ${i + 1} ` + 'lorem ipsum '.repeat(30),
  }));
  await request.post('/test/seed', { data: { conversations: [{ title: 'Long', messages }] } });
  await page.goto('/');
  await page.click('#menu-btn');
  await page.locator('.conversation-item-wrapper', { hasText: 'Long' }).click();
  await page.waitForTimeout(800);
  await page.locator('#messages').hover();
  await page.mouse.wheel(0, -3000);
  await expect(page.locator('.scroll-to-bottom')).toBeVisible();

  await page.locator('.scroll-to-bottom').tap();
  // Late content at the end, as the animation finishes
  // Just after the scroll "ended" (the suite runs with reduced motion: a jump)
  await page.waitForTimeout(250);
  await page.evaluate(() => {
    const last = [...document.querySelectorAll<HTMLElement>('#messages .message')].pop()!;
    const block = document.createElement('div');
    block.style.height = '400px';
    last.querySelector('.message-content')!.appendChild(block);
  });
  await page.waitForTimeout(1200);

  const distance = await page.evaluate(() => {
    const c = document.getElementById('messages')!;
    return c.scrollHeight - c.scrollTop - c.clientHeight;
  });
  expect(distance).toBeLessThan(2);
  await expect(page.locator('.scroll-to-bottom')).toBeHidden();
});
