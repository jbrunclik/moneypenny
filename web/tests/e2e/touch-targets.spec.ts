/**
 * Touch screens get 44px hit areas on the small composer/header controls.
 */
import { test, expect } from '../global-setup';

test.use({ viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true });

test('small controls answer taps within a 44px area', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#menu-btn');
  for (const id of ['attach-btn', 'toolbar-options-btn', 'send-btn', 'menu-btn']) {
    const hit = await page.evaluate((id) => {
      const btn = document.getElementById(id)!;
      const r = btn.getBoundingClientRect();
      // Just outside the drawn button (it is under 44px), vertically centred
      const y = r.top + r.height / 2;
      const x = r.left + r.width / 2;
      const reach = 22 - 2; // inside the 44px area, outside a 30-36px button
      const above = document.elementFromPoint(x, y - reach);
      return { size: Math.round(r.height), above: !!above && (above === btn || btn.contains(above)) };
    }, id);
    expect(hit.size, `${id} draws under 44px (else this test proves nothing)`).toBeLessThan(44);
    expect(hit.above, `${id} hit area`).toBe(true);
  }
});
