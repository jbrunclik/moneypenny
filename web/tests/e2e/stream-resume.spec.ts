/**
 * E2E tests for resumable streams (journal + resume endpoint + client reconnect).
 *
 * The E2E server runs the REAL streaming pipeline (only the LLM is mocked), so
 * the stream journal and the resume endpoint are live. A mid-stream connection
 * drop is simulated by letting the POST /chat/stream request reach the real
 * server (the turn completes and is journaled server-side) while truncating
 * the response body the client sees - exactly what a network drop looks like
 * from the client.
 *
 * Scenarios:
 * 1. Drop mid-stream -> client resumes from its seq offset -> full message,
 *    no incomplete state.
 * 2. Resume endpoint unavailable (404) -> instant fallback to poll recovery
 *    -> message recovered.
 * 3. Resume reports RESUME_FAILED and the message is gone -> incomplete UX.
 *
 * Server-side timeout/crash paths (producer deadline, consumer backstop,
 * dead-producer stall) are covered by unit tests in
 * tests/unit/test_stream_resume.py and test_chat_streaming_timeout.py -
 * they need server-wide config changes that would race other E2E specs.
 */
import { test, expect } from '../global-setup';

/**
 * Intercept the next POST /chat/stream, let the REAL server process it fully,
 * but deliver only the first `keepEvents` SSE events to the client.
 * Returns after installing the route; unroutes itself after one use.
 */
async function truncateNextStream(page: import('@playwright/test').Page, keepEvents: number): Promise<void> {
  await page.route(
    '**/chat/stream',
    async (route) => {
      // route.fetch() buffers the full (mock-fast) SSE response - the real
      // server has journaled everything and saved the message by then
      const response = await route.fetch();
      const body = await response.text();
      const events = body.split('\n\n').filter((e) => e.trim() !== '');
      const truncated = events.slice(0, keepEvents).join('\n\n') + '\n\n';
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
        body: truncated,
      });
    },
    { times: 1 }
  );
}

test.describe('Resumable streams', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Enable streaming
    const streamBtn = page.locator('#stream-btn');
    if ((await streamBtn.getAttribute('aria-pressed')) === 'false') {
      await streamBtn.click();
    }
  });

  test('connection drop mid-stream resumes from offset to full message', async ({ page }) => {
    // Keep user_message_saved + a couple of token events, drop the rest
    await truncateNextStream(page, 3);

    const resumeRequest = page.waitForRequest((req) =>
      req.url().includes('/resume?after_seq=')
    );

    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Resume me please this is a long enough message');
    await page.click('#send-btn');

    // The client must hit the resume endpoint with a non-zero offset
    // (it rendered journaled token events before the drop)
    const req = await resumeRequest;
    const afterSeq = Number(new URL(req.url()).searchParams.get('after_seq'));
    expect(afterSeq).toBeGreaterThan(0);

    // The message completes via resume - full mock response, not a fragment
    await expect(page.locator('.message.assistant:not(.streaming)').last()).toBeVisible({
      timeout: 15000,
    });
    const content = page.locator('.message.assistant').last().locator('.message-content');
    await expect(content).toContainText('This is a mock response to: Resume me please', {
      timeout: 15000,
    });

    // No incomplete styling, no failure toast
    await expect(page.locator('.message.assistant.message-incomplete')).toHaveCount(0);
    await expect(page.locator('.toast-error:has-text("incomplete")')).toHaveCount(0);
  });

  test('resume endpoint 404 falls back to poll recovery', async ({ page }) => {
    await truncateNextStream(page, 3);

    // Simulate an old server / swept journal: resume does not exist
    await page.route('**/resume?after_seq=*', (route) =>
      route.fulfill({ status: 404, contentType: 'application/json', body: '{"error": "Not found"}' })
    );

    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Fallback to polling please');
    await page.click('#send-btn');

    // Poll recovery fetches the saved message (the real turn completed
    // server-side) and finalizes it
    await expect(page.locator('.message.assistant:not(.streaming)').last()).toBeVisible({
      timeout: 30000,
    });
    const content = page.locator('.message.assistant').last().locator('.message-content');
    await expect(content).toContainText('This is a mock response to: Fallback to polling', {
      timeout: 30000,
    });
    await expect(page.locator('.message.assistant.message-incomplete')).toHaveCount(0);
  });

  test('page reload mid-stream resumes the turn from the journal', async ({ page, request }) => {
    // Slow the mock stream down so the turn is still running server-side when
    // the page dies. The `request` fixture carries X-Test-Execution-Id, so the
    // delay applies only to this test's isolated config (page.request would
    // mutate the global default and leak into parallel tests).
    await request.post('/test/set-stream-delay', { data: { delay_ms: 400 } });

    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Survive a reload please');
    await page.click('#send-btn');

    // Wait until the stream is live and the placeholder id is known
    // (persisted to localStorage at user_message_saved)
    await page.waitForSelector('.message.assistant.streaming', { timeout: 10000 });
    await page.waitForFunction(() => localStorage.getItem('inflight-streams') !== null);

    // Simulate a client crash: full page reload mid-stream. The hash route
    // reopens the conversation; the in-flight entry triggers a resume.
    await page.reload();
    await page.waitForSelector('#new-chat-btn');

    await expect(page.locator('.message.assistant:not(.streaming)').last()).toBeVisible({
      timeout: 30000,
    });
    const content = page.locator('.message.assistant').last().locator('.message-content');
    await expect(content).toContainText('This is a mock response to: Survive a reload', {
      timeout: 30000,
    });
    await expect(page.locator('.message.assistant.message-incomplete')).toHaveCount(0);

    // The entry is cleared once the resume reaches a terminal outcome
    const entry = await page.evaluate(() => localStorage.getItem('inflight-streams'));
    expect(entry).toBeNull();
  });

  test('second reload mid-resume still resumes the turn', async ({ page, request }) => {
    await request.post('/test/set-stream-delay', { data: { delay_ms: 400 } });

    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Survive two reloads please');
    await page.click('#send-btn');

    await page.waitForSelector('.message.assistant.streaming', { timeout: 10000 });
    await page.waitForFunction(() => localStorage.getItem('inflight-streams') !== null);

    // First reload: the resume kicks in and shows a live streaming bubble
    await page.reload();
    await page.waitForSelector('.message.assistant.streaming', { timeout: 10000 });

    // The entry must survive while the resume is in flight - clearing it
    // up front made a second reload silently abandon the running turn
    expect(await page.evaluate(() => localStorage.getItem('inflight-streams'))).not.toBeNull();

    // Second reload, mid-resume: the turn must still be picked up
    await page.reload();
    await page.waitForSelector('#new-chat-btn');

    await expect(page.locator('.message.assistant:not(.streaming)').last()).toBeVisible({
      timeout: 30000,
    });
    const content = page.locator('.message.assistant').last().locator('.message-content');
    await expect(content).toContainText('This is a mock response to: Survive two reloads', {
      timeout: 30000,
    });
    await expect(page.locator('.message.assistant.message-incomplete')).toHaveCount(0);

    // Terminal outcome reached: entry cleared after delivery
    await page.waitForFunction(() => localStorage.getItem('inflight-streams') === null);
  });

  test('background/foreground mid-stream aborts the reader and resumes', async ({ page, request }) => {
    await request.post('/test/set-stream-delay', { data: { delay_ms: 400 } });

    const resumeRequest = page.waitForRequest((req) => req.url().includes('/resume?after_seq='));

    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Background me mid-stream please');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant.streaming', { timeout: 10000 });
    // Wait until the placeholder id is known (user_message_saved processed) -
    // proactive resume needs it
    await page.waitForFunction(() => localStorage.getItem('inflight-streams') !== null);

    // Background the app (iOS lock / app switch)...
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    // ...stay hidden past the quick-flicker guard (500ms)...
    await page.waitForTimeout(700);
    // ...and foreground: the client must abort the (possibly dead) reader and
    // resume from its journal offset instead of waiting for a read timeout
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await resumeRequest;

    await expect(page.locator('.message.assistant:not(.streaming)').last()).toBeVisible({
      timeout: 30000,
    });
    const content = page.locator('.message.assistant').last().locator('.message-content');
    await expect(content).toContainText('This is a mock response to: Background me mid-stream', {
      timeout: 30000,
    });
    await expect(page.locator('.message.assistant.message-incomplete')).toHaveCount(0);
    await expect(page.locator('.toast-info:has-text("Response stopped")')).toHaveCount(0);
  });

  test('dead turn (RESUME_FAILED + message gone) shows incomplete state', async ({ page }) => {
    await truncateNextStream(page, 3);

    // Resume says the turn is unrecoverable...
    await page.route('**/resume?after_seq=*', (route) =>
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
        body:
          'data: {"type": "error", "code": "RESUME_FAILED", "message": "The response could not be recovered.", "retryable": false}\n\n',
      })
    );
    // ...and the poll-recovery fallback finds no message either (placeholder
    // deleted after a failed turn)
    await page.route('**/api/messages/*', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: '{"error": "Not found"}',
        });
      }
      return route.fallback();
    });

    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'This turn is going to die');
    await page.click('#send-btn');

    // The client must surface the failure instead of hanging: either the
    // incomplete-styled bubble (partial tokens were rendered) or the
    // "may be incomplete" toast from the recovery module
    await expect(
      page
        .locator('.message.assistant.message-incomplete')
        .or(page.locator('.toast-error:has-text("incomplete")'))
        .first()
    ).toBeVisible({ timeout: 30000 });
  });
});
