/**
 * Inline artifacts: the agent's sandboxed HTML/JS under its reply
 * (docs/features/artifacts.md). The mock turn runs the real create/update
 * tools (/test/set-artifact), so the frame route, CSP, bridge and saved
 * state are the real ones.
 */
import { readFileSync } from 'fs';
import type { APIRequestContext, FrameLocator, Page } from '@playwright/test';
import { test, expect } from '../../global-setup';

// Playwright runs from web/ (the same relative-path style as attachments.spec.ts)
const KITCHEN_SINK = readFileSync('tests/fixtures/artifact-kitchen-sink.html', 'utf8');

async function artifactTurn(
  page: Page,
  request: APIRequestContext,
  artifact: { title?: string; html: string; update?: boolean },
  message = 'Svíčková recipe please',
  newChat = true
): Promise<void> {
  // After the page fixture's reset, which clears the test's mock config
  await request.post('/test/set-artifact', { data: artifact });
  if (newChat) {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    // On mobile, New chat lives in the sidebar
    if (await page.locator('#menu-btn').isVisible()) await page.click('#menu-btn');
    await page.click('#new-chat-btn');
  }
  await page.fill('#message-input', message);
  await page.click('#send-btn');
}

const frameOf = (page: Page, index = 0): FrameLocator =>
  page.locator('.artifact-frame').nth(index).contentFrame();

test.describe('Artifacts', () => {
  test('the reply shows the artifact, sized to its content', async ({ page, request }) => {
    await artifactTurn(page, request, { title: 'Svíčková', html: KITCHEN_SINK });
    const card = page.locator('.message.assistant .artifact-card').last();
    await expect(card.locator('.artifact-card__title')).toHaveText('Svíčková', { timeout: 15000 });
    await expect(frameOf(page).locator('h2')).toHaveText('Svíčková for four');
    await expect.poll(async () => (await card.locator('.artifact-frame').boundingBox())?.height ?? 0).toBeGreaterThan(400);
  });

  test('the frame cannot reach the network or navigate the app', async ({ page, request }) => {
    await artifactTurn(page, request, { title: 'Svíčková', html: KITCHEN_SINK });
    await expect(frameOf(page).locator('#net')).toHaveText('blocked', { timeout: 15000 });
    await expect(frameOf(page).locator('#top')).toHaveText('blocked');
    expect(new URL(page.url()).pathname).not.toBe('/escaped');
  });

  test('the frame follows the app theme', async ({ page, request }) => {
    await artifactTurn(page, request, { title: 'Svíčková', html: KITCHEN_SINK });
    const html = frameOf(page).locator('html');
    // The app is dark without the attribute, light with data-theme="light"
    const appTheme = () =>
      page.evaluate(() => (document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'));
    await expect(html).toHaveAttribute('data-theme', await appTheme(), { timeout: 15000 });
    await page.evaluate(() => {
      const root = document.documentElement;
      if (root.getAttribute('data-theme') === 'light') root.removeAttribute('data-theme');
      else root.setAttribute('data-theme', 'light');
    });
    await expect(html).toHaveAttribute('data-theme', await appTheme());
  });

  test('more escapes are blocked: remote images and popups', async ({ page, request }) => {
    const html = [
      '<p>img: <span id="img">pending</span> · popup: <span id="popup">pending</span></p>',
      '<script>',
      'document.addEventListener("securitypolicyviolation", (e) => {',
      '  if (e.violatedDirective.startsWith("img-src")) img.textContent = "blocked";',
      '});',
      'const probe = new Image();',
      'probe.onload = () => { img.textContent = "open" };',
      'probe.onerror = () => { img.textContent = "blocked" };',
      'probe.src = "https://example.com/pixel.png?d=secret";',
      'popup.textContent = window.open("https://example.com/") ? "open" : "blocked";',
      '</script>',
    ].join('');
    // WebKit fires no securitypolicyviolation for it: no response is the proof
    // (Chromium reports the refused request itself, which never reaches the network)
    const remote: string[] = [];
    page.on('response', (r) => {
      if (r.url().includes('example.com')) remote.push(r.url());
    });
    await artifactTurn(page, request, { title: 'Probes', html });
    await expect(frameOf(page).locator('#img')).toHaveText('blocked', { timeout: 15000 });
    expect(remote).toEqual([]);
    await expect(frameOf(page).locator('#popup')).toHaveText('blocked');
    expect(page.context().pages()).toHaveLength(1);
  });

  test('a full document keeps its body attributes and window load listeners', async ({ page, request }) => {
    const html =
      '<!doctype html><html lang="cs"><body class="recipe"><p id="o">-</p>' +
      '<script>window.addEventListener("DOMContentLoaded", () => { o.textContent = document.body.className })</script>' +
      '</body></html>';
    await artifactTurn(page, request, { title: 'Doc', html });
    await expect(frameOf(page).locator('#o')).toHaveText('recipe', { timeout: 15000 });
    await expect(frameOf(page).locator('html')).toHaveAttribute('lang', 'cs');
  });

  test('a button in the artifact sends a message as the user', async ({ page, request }) => {
    await artifactTurn(page, request, { title: 'Svíčková', html: KITCHEN_SINK });
    // A send while the reply is still running is refused ("Please wait..."):
    // wait for the finalized reply (WebKit can hold the last SSE chunk)
    await expect(page.locator('.message.assistant .message-actions').last()).toBeVisible({ timeout: 15000 });
    // Clear of the floating composer
    await page.locator('.artifact-frame').first().evaluate((f) => f.scrollIntoView({ block: 'start' }));
    await frameOf(page).locator('#scale').click({ timeout: 15000 });
    await expect(page.locator('.message.user').last()).toContainText('Scale to 6');
  });

  test('artifact code cannot send a message without a click', async ({ page, request }) => {
    // Skips mp.send's own check by posting the bridge message directly
    const html =
      '<p id="ok">ready</p><script>setTimeout(() => parent.postMessage({ type: "mp:send", text: "forged send" }, "*"), 300)</script>';
    await artifactTurn(page, request, { title: 'Forged', html });
    await expect(frameOf(page).locator('#ok')).toHaveText('ready', { timeout: 15000 });
    await page.waitForTimeout(1500);
    await expect(page.locator('.message.user', { hasText: 'forged send' })).toHaveCount(0);
  });

  test('ticked items survive a reload', async ({ page, request }) => {
    await artifactTurn(page, request, { title: 'Svíčková', html: KITCHEN_SINK });
    const boxes = frameOf(page).locator('.mp-checklist input');
    await boxes.nth(1).check({ timeout: 15000 });
    // The save is debounced: wait for it before reloading
    await page.waitForResponse((r) => r.url().includes('/state') && r.request().method() === 'PUT');
    await page.reload();
    await expect(frameOf(page).locator('.mp-checklist input').nth(1)).toBeChecked({ timeout: 15000 });
    await expect(frameOf(page).locator('.mp-checklist input').nth(0)).not.toBeChecked();
  });

  test('a revision shows "newer below" on the first version', async ({ page, request }) => {
    await artifactTurn(page, request, { title: 'Tips', html: '<p class="v">one</p>' }, 'Tip calculator');
    await expect(frameOf(page, 0).locator('.v')).toHaveText('one', { timeout: 15000 });
    await artifactTurn(page, request, { html: '<p class="v">two</p>', update: true }, 'Add 15 %', false);
    await expect(frameOf(page, 1).locator('.v')).toHaveText('two', { timeout: 15000 });

    const badge = page.locator('.artifact-card').first().locator('.artifact-card__newer');
    await expect(badge).toHaveText('v1 · newer below');
    await expect(page.locator('.artifact-card').nth(1).locator('.artifact-card__newer')).toHaveCount(0);
    await badge.click();
    await expect(page.locator('.artifact-card').nth(1)).toHaveClass(/artifact-card--flash/);
  });

  test('a runtime error shows a badge and the artifact keeps working', async ({ page, request }) => {
    const html = '<p id="ok">alive</p><script>throw new Error("broken")</script><script>ok.textContent = "still alive"</script>';
    await artifactTurn(page, request, { title: 'Broken', html });
    await expect(frameOf(page).locator('#ok')).toHaveText('still alive', { timeout: 15000 });
    await expect(page.locator('.artifact-card__error')).toHaveText('Artifact error');
  });
});

test.describe('Artifacts on mobile', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('the artifact fills the column and stacks its rows', async ({ page, request }) => {
    await artifactTurn(page, request, { title: 'Svíčková', html: KITCHEN_SINK });
    const frame = frameOf(page);
    await expect(frame.locator('h2')).toHaveText('Svíčková for four', { timeout: 15000 });
    // Both widths from ONE layout: two boundingBox() calls straddled the
    // frame growing to its content - the list then turned scrollable, its
    // 8px styled scrollbar narrowed everything, and one read was 8px wider
    // than the other (WebKit on Linux CI)
    const widths = await page.evaluate(() => {
      const cards = document.querySelectorAll('.artifact-card');
      const contents = document.querySelectorAll('.message.assistant .message-content');
      const card = cards[cards.length - 1];
      const content = contents[contents.length - 1];
      if (!card || !content) throw new Error('no artifact card or message content');
      return {
        card: card.getBoundingClientRect().width,
        content: content.getBoundingClientRect().width,
      };
    });
    expect(Math.abs(widths.card - widths.content)).toBeLessThan(2);
    const direction = await frame.locator('.mp-row').first().evaluate((el) => getComputedStyle(el).flexDirection);
    expect(direction).toBe('column');
    const overflow = await frame.locator('html').evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
