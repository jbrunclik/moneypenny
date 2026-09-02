/**
 * Visual regression tests for error handling UI components
 */
import { test, expect } from '../global-setup';
import type { Page } from '@playwright/test';

/**
 * Helper to dismiss any overlays that might interfere with tests
 */
async function dismissOverlays(page: Page): Promise<void> {
  // Hide version banner via JavaScript (clicking can fail if outside viewport)
  await page.evaluate(() => {
    const banner = document.querySelector('.version-banner');
    if (banner) {
      (banner as HTMLElement).style.display = 'none';
    }
  });
}

test.describe('Visual: Toast Notifications', () => {
  test('success toast', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await dismissOverlays(page);

    // Inject a success toast directly (clipboard may not work in headless browser)
    await page.evaluate(() => {
      const container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'toast-container';
      container.innerHTML = `
        <div class="toast toast-success" role="alert">
          <span class="toast-icon"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg></span>
          <span class="toast-message">Message copied to clipboard!</span>
          <button class="toast-dismiss" aria-label="Dismiss"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>
        </div>
      `;
      const existing = document.getElementById('toast-container');
      if (existing) existing.remove();
      document.body.appendChild(container);
    });

    await page.waitForTimeout(300);

    await expect(page.locator('.toast-container')).toHaveScreenshot('toast-success.png');
  });

  test('error toast', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await dismissOverlays(page);

    // Inject the error toast directly
    await page.evaluate(() => {
      const container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'toast-container';
      container.innerHTML = `
        <div class="toast toast-error" role="alert">
          <span class="toast-icon"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></span>
          <span class="toast-message">Failed to send message. Network error.</span>
          <button class="toast-action">Retry</button>
          <button class="toast-dismiss" aria-label="Dismiss"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>
        </div>
      `;
      const existing = document.getElementById('toast-container');
      if (existing) existing.remove();
      document.body.appendChild(container);
    });

    await page.waitForTimeout(300);

    await expect(page.locator('.toast-container')).toHaveScreenshot('toast-error-with-retry.png');
  });

  test('warning toast', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await dismissOverlays(page);

    // Inject a warning toast directly
    await page.evaluate(() => {
      const container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'toast-container';
      container.innerHTML = `
        <div class="toast toast-warning" role="alert">
          <span class="toast-icon"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg></span>
          <span class="toast-message">File type not supported. Only images, PDFs, and text files are allowed.</span>
          <button class="toast-dismiss" aria-label="Dismiss"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>
        </div>
      `;
      const existing = document.getElementById('toast-container');
      if (existing) existing.remove();
      document.body.appendChild(container);
    });

    await page.waitForTimeout(300);

    await expect(page.locator('.toast-container')).toHaveScreenshot('toast-warning.png');
  });

  test('info toast', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await dismissOverlays(page);

    // Inject an info toast directly
    await page.evaluate(() => {
      const container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'toast-container';
      container.innerHTML = `
        <div class="toast toast-info" role="alert">
          <span class="toast-icon"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg></span>
          <span class="toast-message">Your session will expire in 5 minutes.</span>
          <button class="toast-dismiss" aria-label="Dismiss"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>
        </div>
      `;
      const existing = document.getElementById('toast-container');
      if (existing) existing.remove();
      document.body.appendChild(container);
    });

    await page.waitForTimeout(300);

    await expect(page.locator('.toast-container')).toHaveScreenshot('toast-info.png');
  });

  test('multiple toasts stacked', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await dismissOverlays(page);

    // Inject multiple toasts
    await page.evaluate(() => {
      const container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'toast-container';
      container.innerHTML = `
        <div class="toast toast-error" role="alert">
          <span class="toast-icon"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></span>
          <span class="toast-message">Failed to save changes.</span>
          <button class="toast-dismiss" aria-label="Dismiss"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>
        </div>
        <div class="toast toast-warning" role="alert">
          <span class="toast-icon"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg></span>
          <span class="toast-message">Connection unstable.</span>
          <button class="toast-dismiss" aria-label="Dismiss"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>
        </div>
        <div class="toast toast-success" role="alert">
          <span class="toast-icon"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg></span>
          <span class="toast-message">Message copied!</span>
          <button class="toast-dismiss" aria-label="Dismiss"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>
        </div>
      `;
      const existing = document.getElementById('toast-container');
      if (existing) existing.remove();
      document.body.appendChild(container);
    });

    await page.waitForTimeout(300);

    await expect(page.locator('.toast-container')).toHaveScreenshot('toast-multiple.png');
  });
});

test.describe('Visual: Modal Dialogs', () => {
  test('alert modal', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await dismissOverlays(page);

    // Inject an alert modal directly
    await page.evaluate(() => {
      const container = document.createElement('div');
      container.id = 'modal-container';
      container.className = 'modal-container';
      container.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <button class="modal-close" aria-label="Close">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
          <h2 class="modal-title">Error</h2>
          <p class="modal-message">An unexpected error occurred. Please try again later.</p>
          <div class="modal-actions">
            <button class="modal-confirm">OK</button>
          </div>
        </div>
      `;
      const existing = document.getElementById('modal-container');
      if (existing) existing.remove();
      document.body.appendChild(container);
    });

    await page.waitForTimeout(300);

    // The modal's bottom edge occasionally lands 1px lower on CI runners
    // (~360px of a 1280x1024 frame); a real regression moves thousands.
    await expect(page.locator('.modal-container')).toHaveScreenshot('modal-alert.png', {
      maxDiffPixels: 512,
    });
  });

  test('confirm modal', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await dismissOverlays(page);

    // Inject a confirm modal directly
    await page.evaluate(() => {
      const container = document.createElement('div');
      container.id = 'modal-container';
      container.className = 'modal-container';
      container.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <button class="modal-close" aria-label="Close">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
          <h2 class="modal-title">Confirm Action</h2>
          <p class="modal-message">Are you sure you want to proceed with this action?</p>
          <div class="modal-actions">
            <button class="modal-cancel">Cancel</button>
            <button class="modal-confirm">Confirm</button>
          </div>
        </div>
      `;
      const existing = document.getElementById('modal-container');
      if (existing) existing.remove();
      document.body.appendChild(container);
    });

    await page.waitForTimeout(300);

    await expect(page.locator('.modal-container')).toHaveScreenshot('modal-confirm.png');
  });

  test('danger confirm modal', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await dismissOverlays(page);

    // Inject a danger confirm modal directly
    await page.evaluate(() => {
      const container = document.createElement('div');
      container.id = 'modal-container';
      container.className = 'modal-container';
      container.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <button class="modal-close" aria-label="Close">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
          <h2 class="modal-title">Delete Conversation</h2>
          <p class="modal-message">Are you sure you want to delete this conversation? This cannot be undone.</p>
          <div class="modal-actions">
            <button class="modal-cancel">Cancel</button>
            <button class="modal-confirm modal-danger">Delete</button>
          </div>
        </div>
      `;
      const existing = document.getElementById('modal-container');
      if (existing) existing.remove();
      document.body.appendChild(container);
    });

    await page.waitForTimeout(300);

    await expect(page.locator('.modal-container')).toHaveScreenshot('modal-danger-confirm.png');
  });

  test('prompt modal', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await dismissOverlays(page);

    // Inject a prompt modal directly
    await page.evaluate(() => {
      const container = document.createElement('div');
      container.id = 'modal-container';
      container.className = 'modal-container';
      container.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <button class="modal-close" aria-label="Close">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
          <h2 class="modal-title">Rename Conversation</h2>
          <p class="modal-message">Enter a new name for this conversation:</p>
          <input type="text" class="modal-input" value="My Conversation" placeholder="Conversation name">
          <div class="modal-actions">
            <button class="modal-cancel">Cancel</button>
            <button class="modal-confirm">Save</button>
          </div>
        </div>
      `;
      const existing = document.getElementById('modal-container');
      if (existing) existing.remove();
      document.body.appendChild(container);
    });

    await page.waitForTimeout(300);

    await expect(page.locator('.modal-container')).toHaveScreenshot('modal-prompt.png');
  });

  test('delete confirmation modal', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await dismissOverlays(page);

    // Create a conversation with a message
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test message for delete');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Wait for conversation to appear in sidebar
    await page.waitForSelector('.conversation-item-wrapper', { timeout: 5000 });

    // Hover over the conversation item (the inner .conversation-item) to reveal delete button
    const convItemWrapper = page.locator('.conversation-item-wrapper').first();
    const convItem = convItemWrapper.locator('.conversation-item');
    await convItem.hover();
    await page.waitForTimeout(200);

    // Click delete button - it's .conversation-delete inside .conversation-item
    const deleteBtn = convItem.locator('.conversation-delete');
    await deleteBtn.click({ force: true });

    // Wait for our custom modal to appear (not native dialog)
    await page.waitForSelector('.modal-container:not(.modal-hidden)', { timeout: 5000 });

    // Wait for animation to complete
    await page.waitForTimeout(300);

    // Deterministic focus state: whether #message-input keeps focus after
    // send varies with load timing, and its focus border is inside this
    // full-viewport shot
    await page.locator('#message-input').blur();

    await expect(page.locator('.modal-container')).toHaveScreenshot('modal-delete-confirmation.png');
  });

  test('modal with page overlay', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await dismissOverlays(page);

    // Create a conversation with a message
    await page.click('#new-chat-btn');
    await page.fill('#message-input', 'Test message');
    await page.click('#send-btn');
    await page.waitForSelector('.message.assistant', { timeout: 10000 });

    // Wait for conversation to appear in sidebar
    await page.waitForSelector('.conversation-item-wrapper', { timeout: 5000 });

    // Hover over the conversation item to reveal delete button
    const convItemWrapper = page.locator('.conversation-item-wrapper').first();
    const convItem = convItemWrapper.locator('.conversation-item');
    await convItem.hover();
    await page.waitForTimeout(200);

    // Click delete button
    const deleteBtn = convItem.locator('.conversation-delete');
    await deleteBtn.click({ force: true });

    // Wait for our custom modal to appear
    await page.waitForSelector('.modal-container:not(.modal-hidden)', { timeout: 5000 });
    await page.waitForTimeout(300);

    // Take full page screenshot to show modal with overlay
    // Deterministic focus state (see delete-confirmation test)
    await page.locator('#message-input').blur();

    await expect(page).toHaveScreenshot('modal-with-overlay-fullpage.png', {
      fullPage: true,
    });
  });
});

test.describe('Visual: Mobile Modal Dialogs', () => {
  test.use({ viewport: { width: 375, height: 812 } }); // iPhone X

  test('mobile alert modal', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await dismissOverlays(page);

    // Inject an alert modal directly
    await page.evaluate(() => {
      const container = document.createElement('div');
      container.id = 'modal-container';
      container.className = 'modal-container';
      container.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <button class="modal-close" aria-label="Close">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
          <h2 class="modal-title">Error</h2>
          <p class="modal-message">An unexpected error occurred. Please try again later.</p>
          <div class="modal-actions">
            <button class="modal-confirm">OK</button>
          </div>
        </div>
      `;
      const existing = document.getElementById('modal-container');
      if (existing) existing.remove();
      document.body.appendChild(container);
    });

    await page.waitForTimeout(300);

    await expect(page).toHaveScreenshot('mobile-modal-alert.png');
  });

  test('mobile danger confirm modal', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await dismissOverlays(page);

    // Inject a danger confirm modal directly
    await page.evaluate(() => {
      const container = document.createElement('div');
      container.id = 'modal-container';
      container.className = 'modal-container';
      container.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <button class="modal-close" aria-label="Close">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
          <h2 class="modal-title">Delete Conversation</h2>
          <p class="modal-message">Are you sure you want to delete this conversation? This cannot be undone.</p>
          <div class="modal-actions">
            <button class="modal-cancel">Cancel</button>
            <button class="modal-confirm modal-danger">Delete</button>
          </div>
        </div>
      `;
      const existing = document.getElementById('modal-container');
      if (existing) existing.remove();
      document.body.appendChild(container);
    });

    await page.waitForTimeout(300);

    await expect(page).toHaveScreenshot('mobile-modal-danger-confirm.png');
  });

  test('mobile prompt modal', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await dismissOverlays(page);

    // Inject a prompt modal directly
    await page.evaluate(() => {
      const container = document.createElement('div');
      container.id = 'modal-container';
      container.className = 'modal-container';
      container.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <button class="modal-close" aria-label="Close">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
          <h2 class="modal-title">Rename Conversation</h2>
          <p class="modal-message">Enter a new name for this conversation:</p>
          <input type="text" class="modal-input" value="My Conversation" placeholder="Conversation name">
          <div class="modal-actions">
            <button class="modal-cancel">Cancel</button>
            <button class="modal-confirm">Save</button>
          </div>
        </div>
      `;
      const existing = document.getElementById('modal-container');
      if (existing) existing.remove();
      document.body.appendChild(container);
    });

    await page.waitForTimeout(300);

    await expect(page).toHaveScreenshot('mobile-modal-prompt.png');
  });

  test('mobile toast notifications', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    await dismissOverlays(page);

    // Inject multiple toasts
    await page.evaluate(() => {
      const container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'toast-container';
      container.innerHTML = `
        <div class="toast toast-error" role="alert">
          <span class="toast-icon"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></span>
          <span class="toast-message">Failed to send message. Network error.</span>
          <button class="toast-action">Retry</button>
          <button class="toast-dismiss" aria-label="Dismiss"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>
        </div>
      `;
      const existing = document.getElementById('toast-container');
      if (existing) existing.remove();
      document.body.appendChild(container);
    });

    await page.waitForTimeout(300);

    await expect(page).toHaveScreenshot('mobile-toast-error.png');
  });
});

test.describe('Visual: Version Banner', () => {
  test('version banner', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Inject version banner directly (visible state)
    await page.evaluate(() => {
      const banner = document.createElement('div');
      banner.className = 'version-banner visible';
      banner.innerHTML = `
        <span class="version-banner-message">
          A new version is available
        </span>
        <div class="version-banner-actions">
          <button class="version-banner-reload">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>
            Reload
          </button>
          <button class="version-banner-dismiss">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            Dismiss
          </button>
        </div>
      `;
      const existing = document.querySelector('.version-banner');
      if (existing) existing.remove();
      document.body.appendChild(banner);
    });

    await page.waitForTimeout(300);

    await expect(page.locator('.version-banner')).toHaveScreenshot('version-banner.png');
  });
});

test.describe('Visual: Mobile Version Banner', () => {
  test.use({ viewport: { width: 375, height: 812 } }); // iPhone X

  test('mobile version banner', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');

    // Inject version banner directly (visible state)
    await page.evaluate(() => {
      const banner = document.createElement('div');
      banner.className = 'version-banner visible';
      banner.innerHTML = `
        <span class="version-banner-message">
          A new version is available
        </span>
        <div class="version-banner-actions">
          <button class="version-banner-reload">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>
            Reload
          </button>
          <button class="version-banner-dismiss">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            Dismiss
          </button>
        </div>
      `;
      const existing = document.querySelector('.version-banner');
      if (existing) existing.remove();
      document.body.appendChild(banner);
    });

    await page.waitForTimeout(300);

    await expect(page).toHaveScreenshot('mobile-version-banner.png');
  });
});
