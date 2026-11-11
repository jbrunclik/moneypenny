/**
 * What the two setup Reviews share at the API edge: one quiet retry when the
 * connection dropped (iOS drops a backgrounded PWA's requests mid-review).
 */
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/http';
import { retryDropped } from '@/api/setup-review';

const dropped = (): ApiError => new ApiError('Network error', 0, { isNetworkError: true });

describe('retryDropped', () => {
  it('runs the call again once after a dropped connection', async () => {
    const call = vi.fn<() => Promise<string>>().mockRejectedValueOnce(dropped()).mockResolvedValueOnce('ok');

    await expect(retryDropped(call)).resolves.toBe('ok');
    expect(call).toHaveBeenCalledTimes(2);
  });

  it('gives up after the second drop, and never retries other errors', async () => {
    const twice = vi.fn<() => Promise<string>>().mockRejectedValue(dropped());
    await expect(retryDropped(twice)).rejects.toBeInstanceOf(ApiError);
    expect(twice).toHaveBeenCalledTimes(2);

    const server = vi.fn<() => Promise<string>>().mockRejectedValue(new ApiError('Bad', 502));
    await expect(retryDropped(server)).rejects.toBeInstanceOf(ApiError);
    expect(server).toHaveBeenCalledTimes(1);
  });
});
