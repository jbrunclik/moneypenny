/**
 * Visual regression tests for stream recovery UI states
 *
 * Tests show recovery states in context (toast + message area) on both desktop and mobile.
 */
import { test, expect } from '../global-setup';
import type { Page } from '@playwright/test';

/** Static loading icon (no animation for deterministic screenshots) */
const LOADING_ICON = `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10" stroke-dasharray="31.4 31.4" stroke-dashoffset="10" transform="rotate(-90 12 12)"/></svg>`;

const CLOSE_ICON = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`;

const CHECK_ICON = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`;

const WARNING_ICON = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`;

/**
 * Dismiss overlays and set up a streaming message
 */
async function setupStreamingMessage(page: Page): Promise<void> {
  // Dismiss version banner
  await page.evaluate(() => {
    const banner = document.querySelector('.version-banner');
    if (banner) (banner as HTMLElement).style.display = 'none';
  });

  // Add a streaming message
  await page.evaluate(() => {
    const messagesContainer = document.getElementById('messages');
    if (!messagesContainer) return;

    messagesContainer.innerHTML = '';

    const userMsg = document.createElement('div');
    userMsg.className = 'message user';
    userMsg.innerHTML = `<div class="message-content"><p>Tell me about computing</p></div>`;
    messagesContainer.appendChild(userMsg);

    const assistantMsg = document.createElement('div');
    assistantMsg.className = 'message assistant streaming';
    assistantMsg.innerHTML = `
      <div class="message-content">
        <p>The history of computing dates back to ancient times...</p>
        <span class="streaming-cursor"></span>
      </div>
    `;
    messagesContainer.appendChild(assistantMsg);
  });
}

/**
 * Set up an incomplete message (recovery failed)
 */
async function setupIncompleteMessage(page: Page): Promise<void> {
  await page.evaluate(() => {
    const banner = document.querySelector('.version-banner');
    if (banner) (banner as HTMLElement).style.display = 'none';
  });

  await page.evaluate(() => {
    const messagesContainer = document.getElementById('messages');
    if (!messagesContainer) return;

    messagesContainer.innerHTML = '';

    const userMsg = document.createElement('div');
    userMsg.className = 'message user';
    userMsg.innerHTML = `<div class="message-content"><p>Tell me about computing</p></div>`;
    messagesContainer.appendChild(userMsg);

    const assistantMsg = document.createElement('div');
    assistantMsg.className = 'message assistant message-incomplete';
    assistantMsg.innerHTML = `
      <div class="message-content">
        <p>The history of computing dates back to ancient times...</p>
      </div>
    `;
    messagesContainer.appendChild(assistantMsg);
  });
}

/**
 * Inject a toast notification
 */
async function injectToast(
  page: Page,
  type: 'info' | 'success' | 'warning' | 'error',
  message: string,
  icon: string,
  actionLabel?: string
): Promise<void> {
  await page.evaluate(
    ({ type, message, icon, actionLabel, CLOSE_ICON }) => {
      const toastContainer =
        document.getElementById('toast-container') ||
        (() => {
          const container = document.createElement('div');
          container.id = 'toast-container';
          container.className = 'toast-container';
          document.body.appendChild(container);
          return container;
        })();

      // Clear existing toasts
      toastContainer.innerHTML = '';

      const toast = document.createElement('div');
      toast.className = `toast toast-${type}`;
      toast.setAttribute('role', 'alert');

      const actionHtml = actionLabel
        ? `<button class="toast-action">${actionLabel}</button>`
        : '';

      toast.innerHTML = `
        <span class="toast-icon">${icon}</span>
        <span class="toast-message">${message}</span>
        ${actionHtml}
        <button class="toast-dismiss" aria-label="Dismiss">${CLOSE_ICON}</button>
      `;
      toastContainer.appendChild(toast);
    },
    { type, message, icon, actionLabel, CLOSE_ICON }
  );
}

// ============================================================================
// Desktop Tests
// ============================================================================

test.describe('Visual: Stream Recovery - Desktop', () => {
  test('recovering in progress', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await setupStreamingMessage(page);
    await injectToast(page, 'info', 'Recovering response...', LOADING_ICON);
    await page.waitForTimeout(300);

    await expect(page).toHaveScreenshot('desktop-recovering.png');
  });

  test('recovery succeeded', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await setupStreamingMessage(page);
    await injectToast(page, 'success', 'Response recovered', CHECK_ICON);
    await page.waitForTimeout(300);

    await expect(page).toHaveScreenshot('desktop-recovery-success.png');
  });

  test('recovery warning', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await setupIncompleteMessage(page);
    await injectToast(page, 'warning', 'Response may be incomplete', WARNING_ICON);
    await page.waitForTimeout(300);

    await expect(page).toHaveScreenshot('desktop-recovery-warning.png');
  });

  test('recovery failed', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await setupIncompleteMessage(page);
    await injectToast(
      page,
      'error',
      'Response may be incomplete. Tap to reload.',
      CLOSE_ICON,
      'Reload'
    );
    await page.waitForTimeout(300);

    await expect(page).toHaveScreenshot('desktop-recovery-failed.png');
  });
});

// ============================================================================
// Mobile Tests
// ============================================================================

test.describe('Visual: Stream Recovery - Mobile', () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test('recovering in progress', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await setupStreamingMessage(page);
    await injectToast(page, 'info', 'Recovering response...', LOADING_ICON);
    await page.waitForTimeout(300);

    await expect(page).toHaveScreenshot('mobile-recovering.png');
  });

  test('recovery succeeded', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await setupStreamingMessage(page);
    await injectToast(page, 'success', 'Response recovered', CHECK_ICON);
    await page.waitForTimeout(300);

    await expect(page).toHaveScreenshot('mobile-recovery-success.png');
  });

  test('recovery warning', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await setupIncompleteMessage(page);
    await injectToast(page, 'warning', 'Response may be incomplete', WARNING_ICON);
    await page.waitForTimeout(300);

    await expect(page).toHaveScreenshot('mobile-recovery-warning.png');
  });

  test('recovery failed', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await setupIncompleteMessage(page);
    await injectToast(
      page,
      'error',
      'Response may be incomplete. Tap to reload.',
      CLOSE_ICON,
      'Reload'
    );
    await page.waitForTimeout(300);

    await expect(page).toHaveScreenshot('mobile-recovery-failed.png');
  });
});
