/**
 * UI capture utility: screenshots the app across the full variant matrix
 * (light/dark x desktop/mobile x main pages) for design review.
 *
 * Usage (dev server running):
 *   node scripts/ui-capture.cjs
 *   CAPTURE_BASE=http://localhost:5173 CAPTURE_CONV='/#/conversations/<id>' node scripts/ui-capture.cjs
 *
 * Output: web/ui-captures/<viewport>-<theme>-<page>.png (gitignored)
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const OUT = path.join(__dirname, '..', 'ui-captures');
fs.mkdirSync(OUT, { recursive: true });

const BASE = process.env.CAPTURE_BASE || 'http://localhost:5173';
const PAGES = [
  { name: 'home', url: '/' },
  { name: 'conversation', url: process.env.CAPTURE_CONV || '/' },
  { name: 'sports', url: '/#/sports' },
  { name: 'agents', url: '/#/agents' },
];

(async () => {
  const browser = await chromium.launch();
  for (const theme of ['light', 'dark']) {
    for (const vp of [
      { name: 'desktop', width: 1440, height: 900, mobile: false },
      { name: 'mobile', width: 390, height: 844, mobile: true },
    ]) {
      const ctx = await browser.newContext({
        viewport: { width: vp.width, height: vp.height },
        deviceScaleFactor: 2,
        isMobile: vp.mobile,
        hasTouch: vp.mobile,
      });
      await ctx.addInitScript((t) => localStorage.setItem('ai-chatbot-color-scheme', t), theme);
      for (const p of PAGES) {
        const page = await ctx.newPage();
        await page.goto(BASE + p.url);
        await page.waitForTimeout(2500);
        await page.screenshot({ path: `${OUT}/${vp.name}-${theme}-${p.name}.png` });
        await page.close();
      }
      await ctx.close();
    }
  }
  await browser.close();
  console.log('captured to', OUT);
})();
