/**
 * Rasterize assets/icon.svg to the PNG sizes the app serves.
 * Run from repo root: node scripts/render_icons.mjs
 * Uses the Playwright Chromium already installed for the web tests.
 */
import { chromium } from '../web/node_modules/playwright/index.mjs';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const svg = readFileSync(resolve('assets/icon.svg'), 'utf8');
// [file, size] - 512-maskable uses the same art (eyes sit in the safe zone)
// avatar.png renders circle-cropped with transparent corners - the chat
// avatar container is a circle that does not clip its contents
const outputs = [
  ['static/avatar.png', 96],
  ['static/icon-180.png', 180],
  ['static/icon-192.png', 192],
  ['static/icon-512.png', 512],
  ['static/icon-512-maskable.png', 512],
];

const browser = await chromium.launch();
const page = await browser.newPage();
for (const [file, size] of outputs) {
  await page.setViewportSize({ width: size, height: size });
  const circle = file.includes('avatar');
  await page.setContent(
    `<style>*{margin:0}body{background:transparent}</style><div style="width:${size}px;height:${size}px;${
      circle ? 'border-radius:50%;overflow:hidden;' : ''
    }">${svg.replace(/width="512" height="512"/, `width="${size}" height="${size}"`)}</div>`
  );
  await page.screenshot({
    path: file,
    clip: { x: 0, y: 0, width: size, height: size },
    omitBackground: circle,
  });
  console.log(`rendered ${file}`);
}
await browser.close();
