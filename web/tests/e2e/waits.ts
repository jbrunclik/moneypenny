/**
 * Condition waits for E2E specs, in place of fixed `waitForTimeout` sleeps
 * (T4): a fixed sleep is too short on a loaded runner and wasted time on an
 * idle one. Keep a fixed wait only where elapsed time is the subject - "nothing
 * moves for N ms", a debounce that must lapse - and say so in a comment.
 */
import type { Page } from '@playwright/test';

/** Wait `count` animation frames: scroll, resize and rAF-deferred handlers have run. */
export async function nextFrames(page: Page, count = 2): Promise<void> {
  await page.evaluate(
    (n) =>
      new Promise<void>((resolve) => {
        const step = (left: number): void => {
          if (left <= 0) resolve();
          else requestAnimationFrame(() => step(left - 1));
        };
        step(n);
      }),
    count
  );
}

/**
 * Wait until an element's scroll position stops moving: a smooth scroll (the
 * send glide, a re-pin) has landed. "Stopped" is the same scrollTop for
 * `stableFrames` frames in a row.
 */
export async function scrollSettled(
  page: Page,
  selector = '#messages',
  { stableFrames = 8, timeoutMs = 5000 }: { stableFrames?: number; timeoutMs?: number } = {}
): Promise<void> {
  const settled = await page.evaluate(
    ({ sel, frames, timeout }) =>
      new Promise<boolean>((resolve) => {
        const el = document.querySelector(sel);
        if (!el) {
          resolve(false);
          return;
        }
        const deadline = performance.now() + timeout;
        let last = el.scrollTop;
        let still = 0;
        const tick = (): void => {
          const now = el.scrollTop;
          still = Math.abs(now - last) < 0.5 ? still + 1 : 0;
          last = now;
          if (still >= frames) resolve(true);
          else if (performance.now() > deadline) resolve(false);
          else requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      }),
    { sel: selector, frames: stableFrames, timeout: timeoutMs }
  );
  if (!settled) throw new Error(`${selector} kept scrolling for ${timeoutMs}ms`);
}

/**
 * The page is ready for a screenshot: every finite CSS animation and
 * transition has finished (an entrance has fully landed - text painted
 * mid-animation antialiases differently from the settled baseline), the web
 * fonts are loaded, and two frames have painted. Infinite animations (loading
 * dots, a pulse) are left running: they would never finish.
 */
export async function screenshotReady(page: Page): Promise<void> {
  await page.evaluate(async () => {
    const finite = document
      .getAnimations()
      .filter((a) => a.effect?.getComputedTiming().iterations !== Infinity);
    await Promise.all(finite.map((a) => a.finished.catch(() => undefined)));
    await document.fonts.ready;
  });
  await nextFrames(page);
}
