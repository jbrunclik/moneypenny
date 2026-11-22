/**
 * No page may be wider than a phone. A one-column grid (`1fr`) cannot shrink
 * below its card's min-content, so a no-wrap line in a card (a long name, the
 * "Last session 2d ago · 53 sessions" meta) pushed the Sports cards and their
 * buttons past the right edge. Every page is loaded with long text and checked
 * for any element that sticks out of the viewport without a clipping parent.
 */
import type { Page } from '@playwright/test';
import { test, expect } from '../global-setup';
import { appReady, pageSettled } from './waits';

const LONG = 'Marathon preparation for the spring season with intervals and long runs';

/** Elements whose right edge passes the viewport and that nothing clips. */
async function overflowingElements(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    const clipped = (el: Element): boolean => {
      for (let p = el.parentElement; p; p = p.parentElement) {
        // Only a horizontal scroller may hold wide content: a full-width
        // overflow:hidden page container just cuts the card off
        const { overflowX } = getComputedStyle(p);
        if (overflowX === 'auto' || overflowX === 'scroll') return true;
      }
      return false;
    };
    const out: string[] = [];
    for (const el of Array.from(document.querySelectorAll('body *'))) {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.right <= width + 1) continue;
      if (getComputedStyle(el).visibility === 'hidden' || clipped(el)) continue;
      // The off-canvas sidebar sits left of the viewport, never right
      out.push(`${el.tagName.toLowerCase()}.${el.className.toString().split(' ').join('.')} right=${Math.round(rect.right)}`);
    }
    // A vertical page scroller computes overflow-x: auto too; one that
    // scrolls sideways hides a too-wide page behind a swipe
    for (const el of Array.from(document.querySelectorAll('body *'))) {
      if (!(el instanceof HTMLElement) || el.scrollWidth <= el.clientWidth + 1) continue;
      const { overflowX } = getComputedStyle(el);
      if (overflowX !== 'auto' && overflowX !== 'scroll') continue;
      out.push(`scroller ${el.tagName.toLowerCase()}.${el.className.toString().split(' ').join('.')} scrollWidth=${el.scrollWidth}`);
    }
    return out;
  });
}

async function expectFitsPhone(page: Page): Promise<void> {
  await pageSettled(page);
  expect(await overflowingElements(page)).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
}

test.describe('Mobile - nothing wider than the phone', () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test('sports programs with a long name', async ({ page }) => {
    await page.request.post('/test/set-sports-programs', {
      data: { programs: [{ id: 'run', name: LONG, emoji: '🏃', created_at: '2026-01-01T00:00:00' }] },
    });
    await page.goto('/#/sports');
    await page.waitForSelector('.sports-program-card');
    await expectFitsPhone(page);
  });

  test('language programs with a long name', async ({ page }) => {
    await page.request.post('/test/set-language-programs', {
      data: { programs: [{ id: 'es', name: LONG, emoji: '🇪🇸', created_at: '2026-01-01T00:00:00' }] },
    });
    await page.goto('/#/language');
    await page.waitForSelector('.language-program-card');
    await expectFitsPhone(page);
  });

  test('agents with a long name', async ({ page }) => {
    await page.request.post('/test/seed-agent', { data: { name: LONG, instructions: LONG } });
    await page.goto('/#/agents');
    await page.waitForSelector('.command-center');
    await expect(page.locator('.command-center')).toContainText(LONG.slice(0, 20));
    await expectFitsPhone(page);
  });

  test('data page with a long namespace and memory', async ({ page }) => {
    const now = new Date().toISOString();
    await page.request.post('/test/set-memories-data', {
      data: { memories: [{ id: 'm1', content: LONG, category: 'goal', created_at: now, updated_at: now }] },
    });
    await page.request.post('/test/set-kv-store-data', {
      data: {
        namespaces: [{ namespace: 'agent:81c0fe14-0cbf-48a1-a5b3-8266bc3b370d', key_count: 1 }],
        keys: { 'agent:81c0fe14-0cbf-48a1-a5b3-8266bc3b370d': [{ key: 'a_rather_long_key_name_for_notes', value: LONG }] },
      },
    });
    await page.goto('/#/storage');
    await expect(page.locator('.main')).toContainText(LONG.slice(0, 20));
    await expectFitsPhone(page);
  });

  for (const route of ['#/planner', '#/archive', '#/trash', '#/settings']) {
    test(`${route} page`, async ({ page }) => {
      await page.request.post('/test/seed', {
        data: { conversations: [{ title: LONG, messages: [{ role: 'user', content: LONG }] }] },
      });
      await page.goto(`/${route}`);
      await appReady(page);
      await expectFitsPhone(page);
    });
  }

  test('chat with a long title', async ({ page }) => {
    await page.request.post('/test/seed', {
      data: {
        conversations: [
          {
            title: LONG,
            messages: [
              { role: 'user', content: LONG },
              { role: 'assistant', content: LONG },
            ],
          },
        ],
      },
    });
    await page.goto('/');
    await appReady(page);
    await page.click('#menu-btn');
    await page.locator('.conversation-item').first().click();
    await page.waitForSelector('.message.assistant');
    await expectFitsPhone(page);
  });
});
