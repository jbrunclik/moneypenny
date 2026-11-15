/**
 * checkAuth at startup (auth/google.ts): only an auth error signs the user
 * out; a network blip, timeout or 5xx keeps the token and retries until the
 * server answers (Nov 15 2026 audit: any /auth/me failure cleared the token
 * and the drafts).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/http';
import { useStore } from '@/state/store';

const me = vi.fn();
vi.mock('@/api/auth', () => ({ auth: { me: () => me() } }));
vi.mock('@/components/Toast', () => ({
  toast: { info: vi.fn(), warning: vi.fn(), loading: vi.fn(() => ({ dismiss: vi.fn() })) },
}));
vi.mock('@/core/push', () => ({ disablePush: vi.fn(async () => undefined) }));

import { checkAuth } from '@/auth/google';
import { toast } from '@/components/Toast';

const USER = { id: 'u1', email: 'a@b.c', name: 'A' };
const networkError = (): ApiError => new ApiError('Network error', 0, { isNetworkError: true });

describe('checkAuth', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    me.mockReset();
    useStore.setState({ token: 'tok', user: null });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('signs in when the server answers', async () => {
    me.mockResolvedValueOnce(USER);
    await expect(checkAuth()).resolves.toBe(true);
    expect(useStore.getState().user?.id).toBe('u1');
  });

  it('signs out on an auth error', async () => {
    me.mockRejectedValueOnce(new ApiError('Expired', 401, { code: 'AUTH_EXPIRED' }));
    await expect(checkAuth()).resolves.toBe(false);
    expect(useStore.getState().token).toBeNull();
    expect(toast.info).toHaveBeenCalled();
  });

  it('keeps the token through a network blip and signs in once the server answers', async () => {
    me.mockRejectedValueOnce(networkError())
      .mockRejectedValueOnce(new ApiError('Bad gateway', 502))
      .mockResolvedValueOnce(USER);
    const result = checkAuth();
    await vi.runAllTimersAsync();
    await expect(result).resolves.toBe(true);
    expect(useStore.getState().token).toBe('tok');
    expect(me).toHaveBeenCalledTimes(3);
    expect(toast.loading).toHaveBeenCalledTimes(1);
  });

  it('retries at once when the browser comes back online', async () => {
    me.mockRejectedValueOnce(networkError()).mockResolvedValueOnce(USER);
    const result = checkAuth();
    await vi.advanceTimersByTimeAsync(0);
    window.dispatchEvent(new Event('online'));
    await vi.advanceTimersByTimeAsync(0);
    await expect(result).resolves.toBe(true);
  });

  it('without a token, a failure is simply signed out', async () => {
    useStore.setState({ token: null });
    me.mockRejectedValueOnce(networkError());
    await expect(checkAuth()).resolves.toBe(false);
    expect(me).toHaveBeenCalledTimes(1);
  });
});
