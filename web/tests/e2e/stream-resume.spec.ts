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
