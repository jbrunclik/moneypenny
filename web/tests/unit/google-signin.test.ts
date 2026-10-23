/**
 * Google Sign-In bootstrap: a blocked or failed Google script must leave the
 * login screen with a way forward, not an empty card.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

const getClientId = vi.fn().mockResolvedValue('client-id');
vi.mock('@/api/auth', () => ({ auth: { getClientId } }));

const gsiScripts = (): NodeListOf<HTMLScriptElement> =>
  document.querySelectorAll('script[src="https://accounts.google.com/gsi/client"]');

describe('Google Sign-In fallback', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    document.body.innerHTML = '<div id="google-login-btn"></div>';
    document.head.innerHTML = '';
    getClientId.mockResolvedValue('client-id');
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

  it('loads Google\'s script on demand, once', async () => {
    // Logged-in page loads never need it, so index.html no longer carries it
    const { initGoogleSignIn } = await import('@/auth/google');
    const { GOOGLE_SCRIPT_TIMEOUT_MS } = await import('@/config');

    const first = initGoogleSignIn();
    const second = initGoogleSignIn();
    await vi.advanceTimersByTimeAsync(GOOGLE_SCRIPT_TIMEOUT_MS + 500);
    await Promise.all([first, second]);

    expect(gsiScripts()).toHaveLength(1);
  });

  it('does not load Google\'s script when sign-in is not configured', async () => {
    getClientId.mockResolvedValue(null);
    const { initGoogleSignIn } = await import('@/auth/google');

    await initGoogleSignIn();

    expect(gsiScripts()).toHaveLength(0);
  });
});
