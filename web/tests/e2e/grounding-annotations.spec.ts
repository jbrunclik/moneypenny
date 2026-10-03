import { test, expect } from '../global-setup';

const ANNOTATIONS = {
  summary: { checked: true, source_count: 1 },
  annotations: [
    { type: 'claim', verdict: 'not_found', quote: 'mock response', prefix: 'This is a ', reason: 'Not in the pages I read.' },
    { type: 'claim', verdict: 'supported', quote: 'This is a', source: 1, source_quote: 'This is' },
  ],
};

for (const streaming of [true, false]) {
  test.describe(`Grounding annotations (${streaming ? 'stream' : 'batch'})`, () => {
    test.beforeEach(async ({ page, request }) => {
      await request.post('/test/set-grounding-result', { data: ANNOTATIONS });
      await page.goto('/');
      await page.waitForSelector('#new-chat-btn');
      const streamBtn = page.locator('#stream-btn');
      if ((await streamBtn.getAttribute('aria-pressed')) !== String(streaming)) await streamBtn.click();
      await page.click('#new-chat-btn');
      await page.fill('#message-input', 'Check my claims please');
      await page.click('#send-btn');
      await expect(page.locator('.grounding-footer')).toHaveText(/1 of 2 claims from sources · 1 without a source/, { timeout: 15000 });
    });

    test('underline opens a card; Look it up sends a follow-up', async ({ page }) => {
      const claim = page.locator('.message.assistant .claim').first();
      await expect(claim).toHaveText('mock response');
      await claim.click();
      await expect(page.locator('#claim-card .claim-card__reason')).toHaveText('Not in the pages I read.');
      await page.locator('#claim-card .claim-card__lookup').click();
      await expect(page.locator('.message.user').last()).toContainText('Look up and verify: mock response');
    });

    test('footer opens the claims list; a row jumps to the claim', async ({ page }) => {
      await page.locator('.grounding-footer').click();
      await expect(page.locator('.claims-sheet__row')).toHaveCount(2);
      await page.locator('.claims-sheet__row').first().click();
      await expect(page.locator('#claims-sheet')).toHaveCount(0);
      await expect(page.locator('.claim.claim--flash')).toHaveCount(1);
    });

    test('annotations survive a reload', async ({ page }) => {
      await page.reload();
      await expect(page.locator('.message.assistant .claim')).toHaveText('mock response', { timeout: 15000 });
      await expect(page.locator('sup.claim-cite')).toHaveText('1');
    });
  });
}

test('claims list is a bottom sheet on mobile', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await request.post('/test/set-grounding-result', { data: ANNOTATIONS });
  await page.goto('/');
  await page.waitForSelector('#menu-btn');
  // On mobile, New chat lives in the sidebar
  await page.click('#menu-btn');
  await page.click('#new-chat-btn');
  await page.fill('#message-input', 'Mobile claims please');
  await page.click('#send-btn');
  await page.locator('.grounding-footer').click({ timeout: 15000 });
  await expect(page.locator('.claims-sheet--sheet .claims-sheet__panel')).toBeVisible();
  const box = await page.locator('.claims-sheet__panel').boundingBox();
  expect(box && box.y + box.height).toBeGreaterThan(800);
});
