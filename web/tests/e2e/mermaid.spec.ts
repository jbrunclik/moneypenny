import { test, expect } from '../global-setup';

const DIAGRAM = 'Here is the flow:\n\n```mermaid\nflowchart LR\n  A[Offer] --> B{Start?}\n  B -->|yes| C[Research]\n  B -->|no| D[Done]\n```\n';

async function reply(page: import('@playwright/test').Page, request: import('@playwright/test').APIRequestContext, response: string): Promise<void> {
  await request.post('/test/set-mock-response', { data: { response } });
  await page.goto('/');
  await page.waitForSelector('#new-chat-btn');
  if (await page.locator('#menu-btn').isVisible()) await page.click('#menu-btn');
  await page.click('#new-chat-btn');
  await page.fill('#message-input', 'Draw it');
  await page.click('#send-btn');
}

test.describe('Mermaid diagrams', () => {
  test('a mermaid block renders as a diagram, and survives a reload', async ({ page, request }) => {
    await reply(page, request, DIAGRAM);
    const diagram = page.locator('.message.assistant .mermaid-diagram svg');
    await expect(diagram).toBeVisible({ timeout: 15000 });
    await expect(diagram).toContainText('Research');
    await expect(page.locator('.message.assistant pre')).toBeHidden();

    await page.reload();
    await expect(page.locator('.message.assistant .mermaid-diagram svg')).toBeVisible({ timeout: 15000 });
  });

  test('an invalid diagram stays a code block', async ({ page, request }) => {
    await reply(page, request, '```mermaid\nthis is not a diagram ->->\n```');
    await expect(page.locator('.message.assistant .code-block-wrapper[data-mermaid="failed"]')).toHaveCount(1, { timeout: 15000 });
    await expect(page.locator('.message.assistant pre')).toBeVisible();
    await expect(page.locator('.message.assistant .mermaid-diagram')).toHaveCount(0);
  });

  test('a diagram fits the screen on mobile', async ({ page, request }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await reply(page, request, DIAGRAM);
    const svg = page.locator('.message.assistant .mermaid-diagram svg');
    await expect(svg).toBeVisible({ timeout: 15000 });
    const box = (await svg.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(390);
  });
});
