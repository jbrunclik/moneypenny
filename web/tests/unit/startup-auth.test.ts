/**
 * Signing in at startup (core/startup/auth.ts): the login overlay, the
 * integration OAuth callbacks, and the UI reset on sign-out.
 */
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => {
  const state = {
    calls: [] as string[],
    authenticated: true,
    loadError: null as Error | null,
    /** A mock that records its name in `calls` */
    rec: (name: string) => vi.fn(() => void state.calls.push(name)),
  };
  return state;
});

vi.mock('@/auth/google', () => ({
  checkAuth: vi.fn(async () => h.authenticated),
  initGoogleSignIn: vi.fn(async () => void h.calls.push('initGoogleSignIn')),
  renderGoogleButton: vi.fn((el: HTMLElement) => {
    h.calls.push('renderGoogleButton');
    el.append(document.createElement('iframe'));
  }),
}));
vi.mock('@/components/messages', () => ({
  renderMessages: h.rec('renderMessages'),
  cleanupOlderMessagesScrollListener: h.rec('cleanupOlderMessagesScrollListener'),
  cleanupNewerMessagesScrollListener: h.rec('cleanupNewerMessagesScrollListener'),
}));
vi.mock('@/components/Sidebar', () => ({
  renderConversationsList: h.rec('renderConversationsList'),
  cleanupInfiniteScroll: h.rec('cleanupInfiniteScroll'),
}));
vi.mock('@/components/Toast', () => ({ toast: { error: vi.fn() } }));
vi.mock('@/router/deeplink', () => ({
  initDeepLinking: h.rec('initDeepLinking'),
  cleanupDeepLinking: h.rec('cleanupDeepLinking'),
  clearConversationHash: h.rec('clearConversationHash'),
}));
vi.mock('@/sync/SyncManager', () => ({ stopSyncManager: h.rec('stopSyncManager') }));
vi.mock('@/core/active-requests', () => ({ abortAllStreamingRequests: h.rec('abortAllStreamingRequests') }));
vi.mock('@/core/conversation-deeplink', () => ({ handleDeepLinkNavigation: vi.fn() }));
vi.mock('@/core/startup/initial-data', () => ({
  loadInitialData: vi.fn(async () => {
    h.calls.push('loadInitialData');
    if (h.loadError) throw h.loadError;
  }),
}));
vi.mock('@/core/startup/initial-route', () => ({ initialRouteFromHash: () => ({ type: 'home' }) }));
vi.mock('@/components/settings/oauth', () => ({
  checkTodoistOAuthCallback: vi.fn(async () => void h.calls.push('todoistCallback')),
  checkCalendarOAuthCallback: vi.fn(async () => void h.calls.push('calendarCallback')),
}));

import { initAuthEvents, startSession } from '@/core/startup/auth';
import { loadInitialData } from '@/core/startup/initial-data';
import { toast } from '@/components/Toast';
import type { InitialRoute } from '@/router/deeplink';

const ROUTE = { type: 'conversation', conversationId: 'c1' } as unknown as InitialRoute;
const overlay = (): HTMLElement => document.getElementById('login-overlay')!;
const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

beforeAll(() => {
  initAuthEvents();
});

beforeEach(() => {
  const loginOverlay = document.createElement('div');
  loginOverlay.id = 'login-overlay';
  loginOverlay.className = 'login-overlay hidden';
  const loginBtn = document.createElement('div');
  loginBtn.id = 'google-login-btn';
  loginBtn.append(document.createElement('span'));
  document.body.replaceChildren(loginOverlay, loginBtn);
  h.calls = [];
  h.authenticated = true;
  h.loadError = null;
  sessionStorage.clear();
  vi.clearAllMocks();
});

describe('startSession', () => {
  it('loads the signed-in user’s data for the initial route', async () => {
    await startSession(ROUTE);
    expect(overlay().classList.contains('hidden')).toBe(true);
    expect(loadInitialData).toHaveBeenCalledWith(ROUTE);
    expect(h.calls).not.toContain('todoistCallback');
  });

  it('finishes an OAuth flow before loading, so the integration shows connected', async () => {
    sessionStorage.setItem('calendar-oauth-state', 'abc');
    await startSession(ROUTE);
    expect(h.calls).toEqual(['todoistCallback', 'calendarCallback', 'loadInitialData']);
  });

  it('shows the sign-in button when signed out, without a stale hash', async () => {
    h.authenticated = false;
    await startSession(ROUTE);
    expect(overlay().classList.contains('hidden')).toBe(false);
    expect(h.calls).toEqual(['clearConversationHash', 'initGoogleSignIn', 'renderGoogleButton']);
    expect(loadInitialData).not.toHaveBeenCalled();
  });
});

describe('auth events', () => {
  it('loads the data for the current hash on sign-in', async () => {
    overlay().classList.remove('hidden');
    window.dispatchEvent(new Event('auth:login'));
    await settle();
    expect(overlay().classList.contains('hidden')).toBe(true);
    expect(loadInitialData).toHaveBeenCalledWith({ type: 'home' });
  });

  it('offers a refresh when the data fails to load after sign-in', async () => {
    h.loadError = new Error('boom');
    window.dispatchEvent(new Event('auth:login'));
    await settle();
    expect(toast.error).toHaveBeenCalledWith(
      'Failed to load data. Please refresh the page.',
      expect.objectContaining({ action: expect.objectContaining({ label: 'Refresh' }) })
    );
  });

  it('on sign-out stops the streams first, then resets the UI and the sign-in button', async () => {
    window.dispatchEvent(new Event('auth:logout'));
    await settle();
    expect(h.calls[0]).toBe('abortAllStreamingRequests');
    expect(h.calls).toEqual([
      'abortAllStreamingRequests',
      'stopSyncManager',
      'cleanupInfiniteScroll',
      'cleanupOlderMessagesScrollListener',
      'cleanupNewerMessagesScrollListener',
      'clearConversationHash',
      'cleanupDeepLinking',
      'renderConversationsList',
      'renderMessages',
      // Initialized before rendering: a session that started signed in never was
      'initGoogleSignIn',
      'renderGoogleButton',
      'initDeepLinking',
    ]);
    expect(overlay().classList.contains('hidden')).toBe(false);
    // The old button is replaced, not doubled
    expect(document.getElementById('google-login-btn')!.children).toHaveLength(1);
    expect(document.querySelector('#google-login-btn span')).toBeNull();
  });
});
