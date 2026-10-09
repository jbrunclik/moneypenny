/**
 * Google Sign-In bootstrap: a blocked or failed Google script must leave the
 * login screen with a way forward, not an empty card.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

vi.mock('@/api/auth', () => ({ auth: { getClientId: vi.fn().mockResolvedValue('client-id') } }));

describe('Google Sign-In fallback', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    document.body.innerHTML = '<div id="google-login-btn"></div>';
    delete (globalThis as { google?: unknown }).google;
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('stops waiting for a script that never loads and offers a retry', async () => {
    const { initGoogleSignIn, renderGoogleButton } = await import('@/auth/google');
    const { GOOGLE_SCRIPT_TIMEOUT_MS } = await import('@/config');

    const init = initGoogleSignIn();
    await vi.advanceTimersByTimeAsync(GOOGLE_SCRIPT_TIMEOUT_MS + 500);
    await init; // resolves - it used to poll forever

    const container = document.getElementById('google-login-btn')!;
    renderGoogleButton(container);
    expect(container.textContent).toContain('couldn’t load');
    expect(container.querySelector('button')?.textContent).toContain('Retry');
  });
});
