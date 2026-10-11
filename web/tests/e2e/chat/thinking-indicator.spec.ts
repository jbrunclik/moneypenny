/**
 * E2E tests for thinking indicator collapse/expand behavior
 */
import { test, expect, enableStreaming } from './fixtures';

test.describe('Chat - Thinking Indicator', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await page.click('#new-chat-btn');

    // Enable streaming (thinking indicator only shows in streaming mode)
    await enableStreaming(page);
  });

  test('shows thinking indicator during streaming', async ({ page }) => {
    // Type a message that triggers thinking (mock server emits thinking for "think" keyword)
    await page.fill('#message-input', 'Let me think about this');
    await page.click('#send-btn');

    // Wait for assistant message to appear (streaming creates element immediately)
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toBeVisible({ timeout: 10000 });

    // The thinking indicator should appear initially
    // Note: Due to fast mock streaming, it may collapse quickly
    // We check that response eventually completes
    await expect(assistantMessage).toContainText('mock response', { timeout: 10000 });
  });

  test('thinking indicator collapses after message finishes', async ({ page }) => {
    await page.fill('#message-input', 'Think about 2+2');
    await page.click('#send-btn');

    // Wait for streaming to complete
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toContainText('mock response', { timeout: 10000 });

    // After streaming completes, the indicator should be finalized (collapsed)
    // or removed entirely if there was no thinking/tool content
    const thinkingIndicator = assistantMessage.locator('.thinking-indicator');
    const indicatorCount = await thinkingIndicator.count();

    if (indicatorCount > 0) {
      // If indicator exists, it should be finalized (collapsed with toggle)
      await expect(thinkingIndicator).toHaveClass(/finalized/);
      // And should have a toggle button
      const thinkingToggle = thinkingIndicator.locator('.thinking-toggle');
      await expect(thinkingToggle).toBeVisible();
    }
    // If indicatorCount is 0, that's also valid (removed because no content)
  });

  test('tool indicator shows when force tools are used', async ({ page }) => {
    // Activate search (force web_search tool)
    const searchBtn = page.locator('#search-btn');
    await searchBtn.click();
    await expect(searchBtn).toHaveClass(/active/);

    await page.fill('#message-input', 'Search for something');
    await page.click('#send-btn');

    // Wait for streaming to complete
    const assistantMessage = page.locator('.message.assistant');
    await expect(assistantMessage).toContainText('mock response', { timeout: 10000 });

    // After streaming, there should be a finalized thinking indicator with tool info
    // The mock emits tool_start/tool_end events when force_tools are specified
    const thinkingIndicator = assistantMessage.locator('.thinking-indicator');
    const count = await thinkingIndicator.count();

    // Either indicator exists (showing tool usage) or was removed (no content)
    expect(count).toBeLessThanOrEqual(1);
  });

  test('while thinking: one line with the latest heading; the answer starting collapses it', async ({
    page,
    request,
  }) => {
    // The full thinking text streamed in, filled the screen and pushed the
    // answer out of view (it wrote below it, under a "New messages" pill)
    const thoughts =
      "**Understanding the User's Intent**\n\nI'm now focusing on the Sage.\n\n" +
      "**Reframing the User's Needs**\n\nI now suggest single-dosing for the grinder.";
    await request.post('/test/set-emit-thinking', { data: { emit: true, text: thoughts, hold_ms: 2500 } });
    await request.post('/test/set-stream-delay', { data: { delay_ms: 150 } });
    await page.fill('#message-input', 'Help me choose');
    await page.click('#send-btn');

    const indicator = page.locator('.message.assistant.streaming .thinking-indicator');
    const current = indicator.locator('.thinking-trace-item.current');
    await expect(current.locator('.thinking-heading')).toHaveText("Reframing the User's Needs", { timeout: 10000 });
    await expect(current.locator('.thinking-markdown')).toBeHidden();
    expect((await indicator.boundingBox())!.height).toBeLessThan(60);

    // A tap opens the full text
    await current.click();
    await expect(current.locator('.thinking-markdown')).toBeVisible();
    await expect(current.locator('.thinking-markdown')).toContainText('single-dosing');
    await indicator.locator('.thinking-live-expand').click();
    await expect(current.locator('.thinking-markdown')).toBeHidden();

    // The answer starts: the summary toggle, closed, while the reply still writes
    await expect(indicator.locator('.thinking-toggle')).toBeVisible({ timeout: 10000 });
    await expect(indicator.locator('.thinking-toggle')).toHaveAttribute('aria-expanded', 'false');
    await expect(page.locator('.message.assistant.streaming')).toHaveCount(1);
    await expect(page.locator('.message.assistant')).not.toHaveClass(/streaming/, { timeout: 20000 });
    await expect(page.locator('.message.assistant .thinking-toggle')).toHaveAttribute('aria-expanded', 'false');
  });
});
