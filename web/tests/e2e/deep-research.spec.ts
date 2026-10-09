import type { APIRequestContext, Page } from '@playwright/test';
import { test, expect } from '../global-setup';

const OFFER = {
  question: 'Transfer a car registration',
  context: 'family of four, Prague',
  sub_questions: ['What do agencies charge?', 'How long does it take?', 'Which documents are needed?'],
};

async function offerTurn(
  page: Page,
  request: APIRequestContext,
  options: { stepMs?: number; runNow?: boolean; message?: string } = {}
): Promise<void> {
  await request.post('/test/set-deep-research', {
    data: { offer: { ...OFFER, run_now: options.runNow ?? false }, step_ms: options.stepMs ?? 150 },
  });
  await page.goto('/');
  await page.waitForSelector('#new-chat-btn');
  await page.click('#new-chat-btn');
  await page.fill('#message-input', options.message ?? 'Help me transfer a car registration');
  await page.click('#send-btn');
}

const card = (page: Page) => page.locator('.message.assistant .research-offer').last();

test.describe('Deep research', () => {
  test('edit the offer, run it, and get a report with a chip and a follow-up', async ({ page, request }) => {
    await offerTurn(page, request);
    await expect(card(page).locator('.research-offer__title')).toHaveText('Research this in depth?', { timeout: 15000 });
    await expect(card(page).locator('.research-offer__item textarea')).toHaveCount(3);

    await card(page).locator('.research-offer__remove').nth(1).click();
    await card(page).locator('.research-offer__add').click();
    await card(page).locator('.research-offer__item textarea').last().fill('Can it be done online?');
    await card(page).locator('.research-offer__start').click();

    await expect(card(page)).toHaveText('Deep research started');
    await expect(page.locator('.message--action .action-row__text').last()).toHaveText(/^Deep research started · 3 questions · ~\d+\s+min$/);
    const panel = page.locator('.research-progress');
    await expect(panel.locator('.research-progress__item')).toHaveCount(3);
    await expect(panel.locator('.research-progress__item').first()).toContainText('What do agencies charge?');
    await expect(panel.locator('.research-progress__finding').first()).toContainText('① Finding 1');
    await expect(panel.locator('.research-progress__item').last()).toContainText('Can it be done online?');

    const report = page.locator('.message.assistant').last();
    await expect(report.locator('.research-chip__text')).toHaveText(/^Deep research · 3 questions · 12 pages · \d+ min$/, { timeout: 15000 });
    await expect(page.locator('.research-progress')).toHaveCount(0);
    await expect(report.locator('sup.claim-cite')).toHaveText('1');
    await expect(report.locator('.research-offer__title')).toHaveText('Research further?');

    await report.locator('.research-chip summary').click();
    await expect(report.locator('.research-chip__body')).toContainText('② Finding 2');

    // The report, its chip and the follow-up survive a reload
    await page.reload();
    const reloaded = page.locator('.message.assistant').last();
    await expect(reloaded.locator('.research-chip summary')).toContainText('3 questions', { timeout: 15000 });
    await expect(reloaded.locator('.research-offer__title')).toHaveText('Research further?');
  });

  test('a reload mid-run resumes the progress panel', async ({ page, request }) => {
    test.setTimeout(60_000);
    await offerTurn(page, request, { stepMs: 1000 });
    await card(page).locator('.research-offer__start').click({ timeout: 15000 });
    await expect(page.locator('.research-progress__item')).toHaveCount(3);
    await page.reload();
    await expect(page.locator('.research-progress__item')).toHaveCount(3, { timeout: 15000 });
    await expect(page.locator('.research-chip summary')).toContainText('3 questions', { timeout: 30000 });
    await expect(page.locator('.message.assistant').last().locator('sup.claim-cite')).toHaveText('1');
  });

  test('Finish now ends the research early', async ({ page, request }) => {
    test.setTimeout(60_000);
    await offerTurn(page, request, { stepMs: 1000 });
    await card(page).locator('.research-offer__start').click({ timeout: 15000 });
    const finish = page.locator('.research-progress__finish');
    await finish.click();
    await expect(page.locator('.research-chip summary')).toContainText('finished early', { timeout: 30000 });
  });

  test('runs over the stream even with streaming turned off', async ({ page, request }) => {
    await offerTurn(page, request);
    await expect(card(page).locator('.research-offer__start')).toBeVisible({ timeout: 15000 });
    const streamBtn = page.locator('#stream-btn');
    if ((await streamBtn.getAttribute('aria-pressed')) === 'true') await streamBtn.click();
    const streamed = page.waitForRequest((r) => r.url().endsWith('/chat/stream') && r.method() === 'POST');
    await card(page).locator('.research-offer__start').click();
    const body = (await streamed).postDataJSON() as { deep_research?: { sub_questions: string[] } };
    expect(body.deep_research?.sub_questions).toEqual(OFFER.sub_questions);
    await expect(page.locator('.research-chip summary')).toContainText('3 questions', { timeout: 15000 });
  });

  test('No thanks removes the offer', async ({ page, request }) => {
    await offerTurn(page, request);
    await card(page).locator('.research-offer__decline').click({ timeout: 15000 });
    await expect(page.locator('.research-offer')).toHaveCount(0);
    await page.reload();
    await expect(page.locator('.message.assistant')).toHaveCount(1, { timeout: 15000 });
    await expect(page.locator('.research-offer')).toHaveCount(0);
  });

  test('an explicit request starts by itself', async ({ page, request }) => {
    await offerTurn(page, request, { runNow: true, message: 'Research the car registration transfer in depth' });
    // The plan shows first, counting down; untouched it starts by itself
    await expect(card(page).locator('.research-offer__countdown')).toContainText('Starting in', { timeout: 15000 });
    await expect(page.locator('.research-chip summary')).toContainText('3 questions', { timeout: 30000 });
    // The offer card follows the run, not stuck on Starting…
    await expect(page.locator('.message.assistant .research-offer').first()).toHaveText(/^Deep research started/);
  });

  test('run_now alone does not start: the user did not ask', async ({ page, request }) => {
    await offerTurn(page, request, { runNow: true });
    await expect(card(page).locator('.research-offer__start')).toBeVisible({ timeout: 15000 });
  });
});

test('deep research on mobile', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await request.post('/test/set-deep-research', { data: { offer: OFFER, step_ms: 150 } });
  await page.goto('/');
  await page.waitForSelector('#menu-btn');
  // On mobile, New chat lives in the sidebar
  await page.click('#menu-btn');
  await page.click('#new-chat-btn');
  await page.fill('#message-input', 'Help me transfer a car registration');
  await page.click('#send-btn');
  const start = card(page).locator('.research-offer__start');
  await expect(start).toBeVisible({ timeout: 15000 });
  const remove = await card(page).locator('.research-offer__remove').first().boundingBox();
  expect(remove!.width).toBeGreaterThanOrEqual(44);
  expect(remove!.height).toBeGreaterThanOrEqual(44);
  await start.click();
  await expect(page.locator('.research-chip summary')).toContainText('3 questions', { timeout: 15000 });
});
