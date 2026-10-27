/**
 * E2E tests for the empty-conversation welcome: greeting and (desktop) the
 * composer centred under it.
 */
import { test, expect } from '../global-setup';
import { appReady } from './waits';

test('desktop composer sits under the greeting, then returns to the bottom on send', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/');
  await appReady(page);
  await page.click('#new-chat-btn');
  await expect(page.locator('.welcome-message h2')).toHaveText(/^What’s on your mind/);

  const pill = page.locator('.input-container');
  const centred = (await pill.boundingBox())!;
  expect(centred.y).toBeLessThan(900 * 0.7);

  await page.fill('#message-input', 'Hello there');
  await page.click('#send-btn');
  await expect(page.locator('.message.user')).toBeInViewport();
  // Slid back to the bottom once the welcome is gone
  await expect
    .poll(async () => {
      const box = (await pill.boundingBox())!;
      return box.y + box.height;
    })
    .toBeGreaterThan(900 - 60);
  await expect(page.locator('.message.assistant:not(.streaming)')).toBeInViewport({ timeout: 15000 });
});

test('mobile keeps the composer at the bottom on an empty conversation', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto('/');
  await appReady(page);
  const box = (await page.locator('.input-container').boundingBox())!;
  expect(box.y + box.height).toBeGreaterThan(812 - 60);
});

// iPad Safari: 100vh is the LARGEST viewport (toolbars hidden), taller than
// innerHeight, which the app lays out to (--app-vh); and with a hardware
// keyboard, focusing shows the shortcut bar, which keyboard-viewport.ts
// reserves as --keyboard-inset. The lift must follow the app's real height,
// or the composer rises over the greeting.
for (const [label, vars] of [
  ['100vh exceeds the real height', { '--app-vh': '560px' }],
  ['the keyboard inset shrinks the app', { '--keyboard-inset': '120px' }],
] as const) {
  test(`desktop composer clears the greeting when ${label}`, async ({ page }) => {
    await page.setViewportSize({ width: 1180, height: 820 });
    await page.goto('/');
    await appReady(page);
    await page.click('#new-chat-btn');
    const heading = page.locator('.welcome-message h2');
    await expect(heading).toHaveText(/^What’s on your mind/);
    const gap = async (): Promise<number> => {
      const h = (await heading.boundingBox())!;
      const pill = (await page.locator('.input-container').boundingBox())!;
      return pill.y - (h.y + h.height);
    };
    // The composer glides up; measure once it has settled
    const settled = (): Promise<unknown> =>
      page.waitForFunction(() => document.getAnimations().length === 0);
    await settled();
    const normalGap = await gap();
    expect(normalGap).toBeGreaterThan(0);
    await page.evaluate((v) => {
      for (const [k, val] of Object.entries(v)) document.documentElement.style.setProperty(k, val);
    }, vars);
    await settled();
    const shrunkGap = await gap();
    expect(shrunkGap).toBeGreaterThan(normalGap - 4);
    expect(shrunkGap).toBeLessThan(normalGap + 4);
  });
}
